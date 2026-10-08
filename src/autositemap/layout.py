from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from autositemap.config import DiagramConfig, ViewportConfig
from autositemap.graph import Graph
from autositemap.screenshot import read_png_dimensions


@dataclass
class LayoutNode:
    state_id: str
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    label_height: float = 60.0


@dataclass
class LayoutPort:
    x: float
    y: float


@dataclass
class LayoutConnection:
    source_id: str
    target_id: str
    label: str
    is_tree_edge: bool
    source_port: LayoutPort = field(default_factory=lambda: LayoutPort(0, 0))
    target_port: LayoutPort = field(default_factory=lambda: LayoutPort(0, 0))


@dataclass
class LayoutResult:
    nodes: dict[str, LayoutNode] = field(default_factory=dict)
    connections: list[LayoutConnection] = field(default_factory=list)
    total_width: float = 0.0
    total_height: float = 0.0


def compute_layout(
    graph: Graph,
    diagram: DiagramConfig,
    screenshots_dir: Path | None = None,
    viewport: ViewportConfig | None = None,
) -> LayoutResult:
    if not graph.states:
        return LayoutResult()

    vp = viewport or ViewportConfig()
    tree_children: dict[str, list[str]] = {}
    for t in graph.transitions:
        if t.is_tree_edge:
            tree_children.setdefault(t.source_state_id, []).append(t.target_state_id)

    for children in tree_children.values():
        children.sort()

    layers: dict[int, list[str]] = {}
    for state in graph.states.values():
        layers.setdefault(state.depth, []).append(state.id)
    for layer in layers.values():
        layer.sort()

    nodes: dict[str, LayoutNode] = {}
    for state in graph.states.values():
        card_width = float(diagram.card_width)
        card_height = _compute_card_height(state, card_width, screenshots_dir, vp)
        nodes[state.id] = LayoutNode(
            state_id=state.id,
            width=card_width,
            height=card_height,
        )

    max_layer_width = 0.0
    for layer_ids in layers.values():
        n = len(layer_ids)
        w = n * diagram.card_width + (n - 1) * diagram.horizontal_gap
        max_layer_width = max(max_layer_width, w)

    y_offset = float(diagram.card_padding)
    sorted_layers = sorted(layers.keys())

    for layer_idx in sorted_layers:
        layer_ids = layers[layer_idx]
        n = len(layer_ids)
        total_width = n * diagram.card_width + (n - 1) * diagram.horizontal_gap
        start_x = diagram.card_padding + (max_layer_width - total_width) / 2

        max_card_total = 0.0
        for i, sid in enumerate(layer_ids):
            node = nodes[sid]
            node.x = start_x + i * (diagram.card_width + diagram.horizontal_gap)
            node.y = y_offset
            total_h = node.height + node.label_height
            max_card_total = max(max_card_total, total_h)

        y_offset += max_card_total + diagram.vertical_gap

    connections: list[LayoutConnection] = []
    for t in graph.transitions:
        src = nodes.get(t.source_state_id)
        tgt = nodes.get(t.target_state_id)
        if not src or not tgt:
            continue

        conn = LayoutConnection(
            source_id=t.source_state_id,
            target_id=t.target_state_id,
            label=t.control_text,
            is_tree_edge=t.is_tree_edge,
        )

        if t.is_tree_edge:
            conn.source_port = LayoutPort(
                x=src.x + src.width / 2,
                y=src.y + src.height + src.label_height,
            )
            conn.target_port = LayoutPort(
                x=tgt.x + tgt.width / 2,
                y=tgt.y,
            )
        else:
            if src.x <= tgt.x:
                conn.source_port = LayoutPort(
                    x=src.x + src.width,
                    y=src.y + (src.height + src.label_height) / 2,
                )
                conn.target_port = LayoutPort(
                    x=tgt.x,
                    y=tgt.y + (tgt.height + tgt.label_height) / 2,
                )
            else:
                conn.source_port = LayoutPort(
                    x=src.x,
                    y=src.y + (src.height + src.label_height) / 2,
                )
                conn.target_port = LayoutPort(
                    x=tgt.x + tgt.width,
                    y=tgt.y + (tgt.height + tgt.label_height) / 2,
                )

        connections.append(conn)

    total_width = max_layer_width + 2 * diagram.card_padding
    total_height = y_offset - diagram.vertical_gap + diagram.card_padding

    return LayoutResult(
        nodes=nodes,
        connections=connections,
        total_width=total_width,
        total_height=total_height,
    )


def _compute_card_height(
    state, card_width: float, screenshots_dir: Path | None, vp: ViewportConfig
) -> float:
    if screenshots_dir and state.screenshot_derivative:
        img_path = screenshots_dir / state.screenshot_derivative
        if img_path.exists():
            try:
                data = img_path.read_bytes()
                w, h = read_png_dimensions(data)
                return card_width * (h / w)
            except (ValueError, ZeroDivisionError):
                pass

    return card_width * (vp.height / vp.width)
