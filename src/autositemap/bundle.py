from __future__ import annotations

import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from autositemap.config import Config
from autositemap.graph import Graph
from autositemap.layout import compute_layout


class BundleError(Exception):
    pass


def create_bundle(
    graph: Graph,
    config: Config,
    crawl_dir: Path,
    bundle_path: Path,
) -> Path:
    screenshots_dir = crawl_dir / "screenshots"
    layout = compute_layout(graph, config.diagram, screenshots_dir, config.viewport)

    manifest = _build_manifest(graph, config, layout)

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

        for state in graph.states.values():
            deriv = state.screenshot_derivative or state.screenshot_filename
            if deriv:
                img_path = screenshots_dir / deriv
                if img_path.exists():
                    zf.write(img_path, f"screenshots/{deriv}")

    validate_bundle(bundle_path)
    return bundle_path


def _build_manifest(graph: Graph, config: Config, layout) -> dict:
    states = []
    for state in graph.states.values():
        node = layout.nodes.get(state.id)
        if not node:
            continue

        url_display = _redact_url(state.url, config.export.redact_url_patterns)
        safe_count = sum(1 for c in state.controls if c.is_safe)
        unsafe_count = len(state.controls) - safe_count

        states.append(
            {
                "id": state.id,
                "url": url_display,
                "title": state.title,
                "label": f"{state.id}: {state.title}" if state.title else state.id,
                "screenshot": (
                    f"screenshots/{state.screenshot_derivative or state.screenshot_filename}"
                    if (state.screenshot_derivative or state.screenshot_filename)
                    else None
                ),
                "x": round(node.x, 1),
                "y": round(node.y, 1),
                "width": round(node.width, 1),
                "height": round(node.height + node.label_height, 1),
                "screenshot_height": round(node.height, 1),
                "controls_summary": (
                    f"{len(state.controls)} controls ({safe_count} safe, {unsafe_count} unsafe)"
                ),
            }
        )

    connections = []
    for conn in layout.connections:
        connections.append(
            {
                "source_id": conn.source_id,
                "target_id": conn.target_id,
                "label": conn.label[:60] if conn.label else "",
                "is_tree_edge": conn.is_tree_edge,
                "source_port": {
                    "x": round(conn.source_port.x, 1),
                    "y": round(conn.source_port.y, 1),
                },
                "target_port": {
                    "x": round(conn.target_port.x, 1),
                    "y": round(conn.target_port.y, 1),
                },
            }
        )

    return {
        "version": 1,
        "site_name": config.site.name,
        "generated_at": datetime.now(UTC).isoformat(),
        "diagram": {
            "card_width": config.diagram.card_width,
            "card_padding": config.diagram.card_padding,
            "horizontal_gap": config.diagram.horizontal_gap,
            "vertical_gap": config.diagram.vertical_gap,
            "font_size": config.diagram.font_size,
            "title_font_size": config.diagram.title_font_size,
        },
        "states": states,
        "connections": connections,
        "summary": {
            "states": graph.state_count,
            "transitions": graph.transition_count,
            "tree_edges": graph.tree_edge_count,
            "cross_links": graph.cross_link_count,
            "termination": graph.termination_reason,
        },
    }


_AUTH_PARAMS = frozenset(
    {
        "access_token",
        "token",
        "auth",
        "auth_token",
        "api_key",
        "apikey",
        "session_id",
        "sessionid",
        "sid",
        "key",
        "secret",
        "password",
        "pwd",
        "credential",
        "jwt",
        "bearer",
        "refresh_token",
        "id_token",
    }
)


def _strip_auth_params(url: str) -> str:
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    changed = False

    new_query = parsed.query
    if parsed.query:
        qs = parse_qs(parsed.query, keep_blank_values=True)
        filtered = {k: v for k, v in qs.items() if k.lower() not in _AUTH_PARAMS}
        if len(filtered) != len(qs):
            new_query = urlencode(filtered, doseq=True)
            changed = True

    new_fragment = parsed.fragment
    if parsed.fragment and "=" in parsed.fragment:
        frag_qs = parse_qs(parsed.fragment, keep_blank_values=True)
        frag_filtered = {k: v for k, v in frag_qs.items() if k.lower() not in _AUTH_PARAMS}
        if len(frag_filtered) != len(frag_qs):
            new_fragment = urlencode(frag_filtered, doseq=True)
            changed = True

    new_userinfo = parsed.netloc
    if "@" in parsed.netloc:
        new_userinfo = parsed.netloc.split("@", 1)[1]
        changed = True

    if not changed:
        return url
    return urlunparse(parsed._replace(query=new_query, fragment=new_fragment, netloc=new_userinfo))


def _redact_url(url: str, patterns: tuple[str, ...]) -> str:
    result = _strip_auth_params(url)
    for pattern in patterns:
        result = re.sub(pattern, "[REDACTED]", result)
    return result


def validate_bundle(bundle_path: Path) -> None:
    if not bundle_path.exists():
        raise BundleError(f"Bundle file not found: {bundle_path}")

    try:
        with zipfile.ZipFile(bundle_path, "r") as zf:
            names = zf.namelist()

            if "manifest.json" not in names:
                raise BundleError("Bundle missing manifest.json")

            manifest = json.loads(zf.read("manifest.json"))

            if manifest.get("version") != 1:
                raise BundleError(f"Unsupported bundle version: {manifest.get('version')}")

            state_ids = {s["id"] for s in manifest.get("states", [])}

            for state in manifest.get("states", []):
                screenshot = state.get("screenshot")
                if screenshot and screenshot not in names:
                    raise BundleError(
                        f"State {state['id']} references missing screenshot: {screenshot}"
                    )

                for coord in ("x", "y", "width", "height"):
                    val = state.get(coord)
                    if val is not None and (not isinstance(val, (int, float)) or val < 0):
                        raise BundleError(f"State {state['id']} has invalid {coord}: {val}")

            for conn in manifest.get("connections", []):
                if conn["source_id"] not in state_ids:
                    raise BundleError(f"Connection references unknown source: {conn['source_id']}")
                if conn["target_id"] not in state_ids:
                    raise BundleError(f"Connection references unknown target: {conn['target_id']}")

    except zipfile.BadZipFile as e:
        raise BundleError(f"Invalid ZIP file: {e}") from e


def validate_bundle_images(bundle_path: Path) -> list[str]:
    warnings = []
    with zipfile.ZipFile(bundle_path, "r") as zf:
        for name in zf.namelist():
            if name.startswith("screenshots/") and name.endswith(".png"):
                data = zf.read(name)
                from autositemap.screenshot import read_png_dimensions

                try:
                    w, h = read_png_dimensions(data)
                    if w > 4096 or h > 4096:
                        warnings.append(f"{name}: {w}x{h} exceeds Figma 4096px limit")
                except ValueError:
                    warnings.append(f"{name}: not a valid PNG")
    return warnings
