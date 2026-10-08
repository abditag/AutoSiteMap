"""AC7 -- Bundle creation, validation, and full-pipeline tests."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from autositemap.bundle import BundleError, create_bundle, validate_bundle
from autositemap.config import Config
from autositemap.crawler import explore
from autositemap.graph import Graph


def test_layout_handles_branching_cycles_and_long_labels(fixture_config: Config, output_dir):
    """Build a graph programmatically with branching (one state with multiple
    children), a cycle (cross-link back to root), and long control text labels
    (>60 chars). Create a bundle. Validate it. Assert manifest has correct
    structure."""
    graph = Graph(config_path=None, started_at="2024-01-01T00:00:00Z")
    graph.finished_at = "2024-01-01T00:05:00Z"
    graph.termination_reason = "frontier_exhausted"

    # Create states: root branches to child_a and child_b, child_a links back to root (cycle)
    root = graph.add_state(url="http://test/", fingerprint_hash="aaa", title="Root Page", depth=0)
    child_a = graph.add_state(
        url="http://test/a", fingerprint_hash="bbb", title="Child A", depth=1
    )
    child_b = graph.add_state(
        url="http://test/b", fingerprint_hash="ccc", title="Child B", depth=1
    )

    # Create screenshots directory and dummy PNGs
    screenshots_dir = output_dir / "screenshots"
    for state in [root, child_a, child_b]:
        png_name = f"{state.id}.png"
        state.screenshot_filename = png_name
        state.screenshot_derivative = png_name
        _write_minimal_png(screenshots_dir / png_name, 800, 600)

    long_label = "A" * 80  # >60 chars

    # Tree edges: root -> child_a, root -> child_b
    graph.add_transition(root.id, child_a.id, "#link-a", long_label, is_tree_edge=True)
    graph.add_transition(root.id, child_b.id, "#link-b", "Go to B", is_tree_edge=True)

    # Cross-link (cycle): child_a -> root
    graph.add_transition(child_a.id, root.id, "#back", "Back to root", is_tree_edge=False)

    bundle_path = output_dir / "test_bundle.zip"
    create_bundle(graph, fixture_config, output_dir, bundle_path)

    # validate_bundle is called inside create_bundle, but call it explicitly too
    validate_bundle(bundle_path)

    # Inspect manifest structure
    with zipfile.ZipFile(bundle_path, "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))

    assert manifest["version"] == 1
    assert manifest["site_name"] == fixture_config.site.name
    assert len(manifest["states"]) == 3
    assert len(manifest["connections"]) == 3

    state_ids = {s["id"] for s in manifest["states"]}
    assert state_ids == {root.id, child_a.id, child_b.id}

    # Long labels should be truncated to 60 chars in connections
    long_conn = [
        c
        for c in manifest["connections"]
        if c["source_id"] == root.id and c["target_id"] == child_a.id
    ]
    assert len(long_conn) == 1
    assert len(long_conn[0]["label"]) <= 60

    # Cross-link should be present
    cross_links = [c for c in manifest["connections"] if not c["is_tree_edge"]]
    assert len(cross_links) == 1
    assert cross_links[0]["source_id"] == child_a.id
    assert cross_links[0]["target_id"] == root.id


def test_bundle_rejects_missing_images_and_dangling_edges(output_dir):
    """Create an invalid bundle ZIP manually (missing a screenshot, or a
    connection referencing nonexistent state). Call validate_bundle and
    assert it raises BundleError."""
    bundle_path = output_dir / "invalid_bundle.zip"

    # Case 1: Connection references a nonexistent state
    manifest_dangling = {
        "version": 1,
        "site_name": "Test",
        "generated_at": "2024-01-01T00:00:00Z",
        "diagram": {},
        "states": [
            {
                "id": "s0",
                "url": "http://test/",
                "title": "Root",
                "label": "s0: Root",
                "screenshot": None,
                "x": 0,
                "y": 0,
                "width": 300,
                "height": 225,
                "screenshot_height": 225,
                "controls_summary": "0 controls",
            },
        ],
        "connections": [
            {
                "source_id": "s0",
                "target_id": "s99",  # does not exist
                "label": "broken",
                "is_tree_edge": True,
                "source_port": {"x": 150, "y": 225},
                "target_port": {"x": 150, "y": 0},
            },
        ],
        "summary": {
            "states": 1,
            "transitions": 1,
            "tree_edges": 1,
            "cross_links": 0,
            "termination": "test",
        },
    }

    with zipfile.ZipFile(bundle_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest_dangling))

    with pytest.raises(BundleError, match="unknown target"):
        validate_bundle(bundle_path)

    # Case 2: State references a screenshot that doesn't exist in the ZIP
    bundle_path2 = output_dir / "missing_image_bundle.zip"
    manifest_missing_img = {
        "version": 1,
        "site_name": "Test",
        "generated_at": "2024-01-01T00:00:00Z",
        "diagram": {},
        "states": [
            {
                "id": "s0",
                "url": "http://test/",
                "title": "Root",
                "label": "s0: Root",
                "screenshot": "screenshots/nonexistent.png",
                "x": 0,
                "y": 0,
                "width": 300,
                "height": 225,
                "screenshot_height": 225,
                "controls_summary": "0 controls",
            },
        ],
        "connections": [],
        "summary": {
            "states": 1,
            "transitions": 0,
            "tree_edges": 0,
            "cross_links": 0,
            "termination": "test",
        },
    }

    with zipfile.ZipFile(bundle_path2, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest_missing_img))

    with pytest.raises(BundleError, match="missing screenshot"):
        validate_bundle(bundle_path2)


@pytest.mark.slow
async def test_full_pipeline_bundle(fixture_config: Config, fixture_server, output_dir):
    """Run a crawl on the fixture site, then create a bundle. Validate it.
    Open the ZIP and verify manifest.json structure, screenshot files exist,
    connections reference valid states."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={
                "width": fixture_config.viewport.width,
                "height": fixture_config.viewport.height,
            },
            service_workers="block",
        )
        page = await context.new_page()
        base_url = fixture_server.base_url

        await context.add_cookies([{"name": "auth", "value": "valid", "url": base_url}])
        await page.goto(f"{base_url}/", wait_until="load")

        graph = await explore(page, fixture_config, output_dir)

        assert graph.state_count >= 1, "Crawl should discover at least the root state"

        bundle_path = output_dir / "full_pipeline.zip"
        create_bundle(graph, fixture_config, output_dir, bundle_path)

        # validate_bundle is called inside create_bundle, but verify explicitly
        validate_bundle(bundle_path)

        # Inspect the ZIP contents
        with zipfile.ZipFile(bundle_path, "r") as zf:
            names = zf.namelist()
            assert "manifest.json" in names

            manifest = json.loads(zf.read("manifest.json"))

            # Verify manifest structure
            assert manifest["version"] == 1
            assert manifest["site_name"] == fixture_config.site.name
            assert isinstance(manifest["states"], list)
            assert isinstance(manifest["connections"], list)
            assert isinstance(manifest["summary"], dict)

            state_ids = {s["id"] for s in manifest["states"]}

            # All connections should reference valid states
            for conn in manifest["connections"]:
                assert conn["source_id"] in state_ids, (
                    f"Connection source {conn['source_id']} not in states"
                )
                assert conn["target_id"] in state_ids, (
                    f"Connection target {conn['target_id']} not in states"
                )

            # All referenced screenshots should be in the ZIP
            for state in manifest["states"]:
                screenshot = state.get("screenshot")
                if screenshot:
                    assert screenshot in names, (
                        f"Screenshot {screenshot} referenced but not in ZIP"
                    )

        await browser.close()


def _write_minimal_png(path: Path, width: int, height: int) -> None:
    """Write a minimal valid PNG file with the given dimensions."""
    import struct
    import zlib

    path.parent.mkdir(parents=True, exist_ok=True)

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)

    # Create minimal image data: one row of black pixels
    raw_data = b""
    for _ in range(height):
        raw_data += b"\x00" + b"\x00" * width * 3  # filter byte + RGB

    compressed = zlib.compress(raw_data)
    idat = _chunk(b"IDAT", compressed)
    iend = _chunk(b"IEND", b"")

    path.write_bytes(signature + ihdr + idat + iend)
