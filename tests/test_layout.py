"""Tests for autositemap.layout — compute_layout algorithm."""

from __future__ import annotations

from autositemap.config import DiagramConfig, ViewportConfig
from autositemap.graph import Graph
from autositemap.layout import LayoutResult, compute_layout

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIAGRAM = DiagramConfig()
_VIEWPORT = ViewportConfig()


def _build_linear_graph(n: int = 3) -> Graph:
    """Build a linear chain: s0 -> s1 -> s2 -> ... with increasing depth."""
    g = Graph()
    for i in range(n):
        g.add_state(
            url=f"https://example.com/page{i}",
            fingerprint_hash=f"fp{i}",
            title=f"Page {i}",
            depth=i,
        )
    for i in range(n - 1):
        g.add_transition(f"s{i}", f"s{i + 1}", f"a[href='/page{i + 1}']", f"Link {i + 1}")
    return g


def _build_branching_graph() -> Graph:
    """s0 branches to s1, s2, s3 (depth 1), s1 branches to s4 (depth 2)."""
    g = Graph()
    g.add_state(url="https://ex.com/", fingerprint_hash="r", title="Root", depth=0)
    g.add_state(url="https://ex.com/a", fingerprint_hash="a", title="A", depth=1)
    g.add_state(url="https://ex.com/b", fingerprint_hash="b", title="B", depth=1)
    g.add_state(url="https://ex.com/c", fingerprint_hash="c", title="C", depth=1)
    g.add_state(url="https://ex.com/d", fingerprint_hash="d", title="D", depth=2)

    g.add_transition("s0", "s1", "a", "A")
    g.add_transition("s0", "s2", "a", "B")
    g.add_transition("s0", "s3", "a", "C")
    g.add_transition("s1", "s4", "a", "D")
    return g


def _bounding_box(node):
    """Return (left, top, right, bottom) for a node including label_height."""
    return (
        node.x,
        node.y,
        node.x + node.width,
        node.y + node.height + node.label_height,
    )


def _boxes_overlap(a, b) -> bool:
    al, at, ar, ab = _bounding_box(a)
    bl, bt, br, bb = _bounding_box(b)
    return not (ar <= bl or br <= al or ab <= bt or bb <= at)


# ---------------------------------------------------------------------------
# test_deterministic_layout
# ---------------------------------------------------------------------------


def test_deterministic_layout():
    """Running layout twice on the same graph yields identical coordinates."""
    g = _build_branching_graph()
    r1 = compute_layout(g, _DIAGRAM, viewport=_VIEWPORT)
    r2 = compute_layout(g, _DIAGRAM, viewport=_VIEWPORT)

    for sid in g.states:
        n1, n2 = r1.nodes[sid], r2.nodes[sid]
        assert n1.x == n2.x
        assert n1.y == n2.y
        assert n1.width == n2.width
        assert n1.height == n2.height

    assert r1.total_width == r2.total_width
    assert r1.total_height == r2.total_height


# ---------------------------------------------------------------------------
# test_no_overlap
# ---------------------------------------------------------------------------


def test_no_overlap():
    """No card bounding boxes overlap in a multi-state layout."""
    g = _build_branching_graph()
    result = compute_layout(g, _DIAGRAM, viewport=_VIEWPORT)

    node_list = list(result.nodes.values())
    for i in range(len(node_list)):
        for j in range(i + 1, len(node_list)):
            assert not _boxes_overlap(node_list[i], node_list[j]), (
                f"Overlap between {node_list[i].state_id} and {node_list[j].state_id}"
            )


# ---------------------------------------------------------------------------
# test_root_at_top
# ---------------------------------------------------------------------------


def test_root_at_top():
    """Root state has the minimum y coordinate."""
    g = _build_branching_graph()
    result = compute_layout(g, _DIAGRAM, viewport=_VIEWPORT)
    root_y = result.nodes[g.root_state_id].y
    for node in result.nodes.values():
        assert node.y >= root_y


# ---------------------------------------------------------------------------
# test_tree_vs_crosslink_ports
# ---------------------------------------------------------------------------


def test_tree_vs_crosslink_ports():
    """Tree edges use top/bottom ports; cross-links use side ports."""
    g = Graph()
    g.add_state(url="https://ex.com/", fingerprint_hash="r", title="Root", depth=0)
    g.add_state(url="https://ex.com/a", fingerprint_hash="a", title="A", depth=1)
    g.add_state(url="https://ex.com/b", fingerprint_hash="b", title="B", depth=1)

    # Tree edges: root -> a, root -> b
    g.add_transition("s0", "s1", "a", "To A", is_tree_edge=True)
    g.add_transition("s0", "s2", "a", "To B", is_tree_edge=True)
    # Cross-link: a -> b
    g.add_transition("s1", "s2", "a", "A->B", is_tree_edge=False)

    result = compute_layout(g, _DIAGRAM, viewport=_VIEWPORT)

    for conn in result.connections:
        src = result.nodes[conn.source_id]
        tgt = result.nodes[conn.target_id]
        if conn.is_tree_edge:
            # Source port at bottom (y = src.y + src.height + label_height)
            assert conn.source_port.y == src.y + src.height + src.label_height
            # Target port at top (y = tgt.y)
            assert conn.target_port.y == tgt.y
        else:
            # Cross-link ports at vertical midpoint (side ports)
            src_mid_y = src.y + (src.height + src.label_height) / 2
            tgt_mid_y = tgt.y + (tgt.height + tgt.label_height) / 2
            assert conn.source_port.y == src_mid_y
            assert conn.target_port.y == tgt_mid_y


# ---------------------------------------------------------------------------
# test_empty_graph_layout
# ---------------------------------------------------------------------------


def test_empty_graph_layout():
    """Empty graph produces an empty layout result."""
    g = Graph()
    result = compute_layout(g, _DIAGRAM, viewport=_VIEWPORT)
    assert isinstance(result, LayoutResult)
    assert result.nodes == {}
    assert result.connections == []
    assert result.total_width == 0.0
    assert result.total_height == 0.0


# ---------------------------------------------------------------------------
# test_single_state_layout
# ---------------------------------------------------------------------------


def test_single_state_layout():
    """Single state is positioned at the padding offset."""
    g = Graph()
    g.add_state(url="https://ex.com/", fingerprint_hash="r", title="Root", depth=0)

    result = compute_layout(g, _DIAGRAM, viewport=_VIEWPORT)

    assert len(result.nodes) == 1
    node = result.nodes["s0"]
    assert node.x == _DIAGRAM.card_padding
    assert node.y == _DIAGRAM.card_padding
    assert node.width == _DIAGRAM.card_width
    assert result.connections == []
