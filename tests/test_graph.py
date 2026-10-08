"""Tests for autositemap.graph — Graph data structure."""

from __future__ import annotations

from autositemap.graph import ControlRecord, Graph

# ---------------------------------------------------------------------------
# test_add_state_and_lookup
# ---------------------------------------------------------------------------


def test_add_state_and_lookup():
    """State IDs are sequential (s0, s1, ...) and fingerprint index works."""
    g = Graph()
    s0 = g.add_state(url="https://example.com/", fingerprint_hash="aaa", title="Home")
    s1 = g.add_state(url="https://example.com/about", fingerprint_hash="bbb", title="About")
    s2 = g.add_state(url="https://example.com/contact", fingerprint_hash="ccc", title="Contact")

    assert s0.id == "s0"
    assert s1.id == "s1"
    assert s2.id == "s2"

    assert g.find_state_by_fingerprint("https://example.com/", "aaa") is s0
    assert g.find_state_by_fingerprint("https://example.com/about", "bbb") is s1
    assert g.find_state_by_fingerprint("https://example.com/contact", "ccc") is s2

    # Non-existent fingerprint returns None
    assert g.find_state_by_fingerprint("https://example.com/", "zzz") is None


# ---------------------------------------------------------------------------
# test_add_transition
# ---------------------------------------------------------------------------


def test_add_transition():
    """Transitions are recorded correctly; tree_edge and cross_link counts work."""
    g = Graph()
    g.add_state(url="https://example.com/", fingerprint_hash="h0")
    g.add_state(url="https://example.com/a", fingerprint_hash="h1")
    g.add_state(url="https://example.com/b", fingerprint_hash="h2")

    t1 = g.add_transition("s0", "s1", "a[href='/a']", "Link A", is_tree_edge=True)
    g.add_transition("s0", "s2", "a[href='/b']", "Link B", is_tree_edge=True)
    t3 = g.add_transition("s1", "s0", "a[href='/']", "Home", is_tree_edge=False)

    assert g.transition_count == 3
    assert g.tree_edge_count == 2
    assert g.cross_link_count == 1

    assert t1.source_state_id == "s0"
    assert t1.target_state_id == "s1"
    assert t1.is_tree_edge is True

    assert t3.is_tree_edge is False


# ---------------------------------------------------------------------------
# test_serialization_roundtrip
# ---------------------------------------------------------------------------


def test_serialization_roundtrip(tmp_path):
    """Save and load preserve all graph data."""
    g = Graph()
    g.config_path = "/some/config.toml"
    g.started_at = "2026-01-01T00:00:00"
    g.finished_at = "2026-01-01T00:05:00"
    g.termination_reason = "frontier_exhausted"

    s0 = g.add_state(url="https://ex.com/", fingerprint_hash="fp0", title="Root", depth=0)
    s0.controls.append(
        ControlRecord(selector="a", tag="a", text="Go", outcome="explored", target_state_id="s1")
    )
    s0.has_iframes = True

    s1 = g.add_state(url="https://ex.com/page", fingerprint_hash="fp1", title="Page", depth=1)
    s1.screenshot_filename = "s1.png"

    g.add_transition("s0", "s1", "a", "Go", is_tree_edge=True)
    g.add_out_of_scope("s0", "https://other.com/", "External Link")

    save_path = tmp_path / "graph.json"
    g.save(save_path)

    loaded = Graph.load(save_path)

    assert loaded.state_count == g.state_count
    assert loaded.transition_count == g.transition_count
    assert loaded.root_state_id == "s0"
    assert loaded.termination_reason == "frontier_exhausted"
    assert loaded.config_path == "/some/config.toml"
    assert loaded.started_at == "2026-01-01T00:00:00"
    assert loaded.finished_at == "2026-01-01T00:05:00"

    # States
    ls0 = loaded.states["s0"]
    assert ls0.title == "Root"
    assert ls0.has_iframes is True
    assert len(ls0.controls) == 1
    assert ls0.controls[0].outcome == "explored"
    assert ls0.controls[0].target_state_id == "s1"

    ls1 = loaded.states["s1"]
    assert ls1.screenshot_filename == "s1.png"
    assert ls1.depth == 1

    # Transitions
    lt = loaded.transitions[0]
    assert lt.source_state_id == "s0"
    assert lt.target_state_id == "s1"
    assert lt.is_tree_edge is True

    # Out of scope
    assert len(loaded.out_of_scope_urls) == 1
    assert loaded.out_of_scope_urls[0]["url"] == "https://other.com/"

    # Fingerprint index rebuilt correctly
    assert loaded.find_state_by_fingerprint("https://ex.com/", "fp0") is not None
    assert loaded.find_state_by_fingerprint("https://ex.com/page", "fp1") is not None

    # _next_state_num restored correctly (new state should be s2)
    s_new = loaded.add_state(url="https://ex.com/new", fingerprint_hash="fpNew")
    assert s_new.id == "s2"


# ---------------------------------------------------------------------------
# test_empty_graph
# ---------------------------------------------------------------------------


def test_empty_graph():
    """An empty graph has 0 states, 0 transitions, no root."""
    g = Graph()
    assert g.state_count == 0
    assert g.transition_count == 0
    assert g.tree_edge_count == 0
    assert g.cross_link_count == 0
    assert g.root_state_id is None


# ---------------------------------------------------------------------------
# test_duplicate_fingerprint_lookup
# ---------------------------------------------------------------------------


def test_duplicate_fingerprint_lookup():
    """Two states with different fingerprints each resolve correctly."""
    g = Graph()
    s0 = g.add_state(url="https://example.com/", fingerprint_hash="hash_a")
    s1 = g.add_state(url="https://example.com/", fingerprint_hash="hash_b")

    assert g.find_state_by_fingerprint("https://example.com/", "hash_a") is s0
    assert g.find_state_by_fingerprint("https://example.com/", "hash_b") is s1
    assert g.find_state_by_fingerprint("https://example.com/", "hash_c") is None


# ---------------------------------------------------------------------------
# test_out_of_scope_tracking
# ---------------------------------------------------------------------------


def test_out_of_scope_tracking():
    """Out-of-scope URLs are recorded and retrievable."""
    g = Graph()
    g.add_state(url="https://example.com/", fingerprint_hash="h0")

    g.add_out_of_scope("s0", "https://external.com/page1", "Ext Link 1")
    g.add_out_of_scope("s0", "https://external.com/page2", "Ext Link 2")
    g.add_out_of_scope("s0", "https://other.com/", "Other")

    assert len(g.out_of_scope_urls) == 3
    urls = [entry["url"] for entry in g.out_of_scope_urls]
    assert "https://external.com/page1" in urls
    assert "https://external.com/page2" in urls
    assert "https://other.com/" in urls

    # Each entry carries source_state_id and control_text
    assert all(entry["source_state_id"] == "s0" for entry in g.out_of_scope_urls)
    assert g.out_of_scope_urls[0]["control_text"] == "Ext Link 1"
