"""Tests for autositemap.report — generate_report."""

from __future__ import annotations

from autositemap.graph import ControlRecord, Graph
from autositemap.report import generate_report

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_control(
    selector: str = "a",
    tag: str = "a",
    text: str = "Link",
    outcome: str | None = None,
    **kwargs,
) -> ControlRecord:
    return ControlRecord(selector=selector, tag=tag, text=text, outcome=outcome, **kwargs)


def _build_graph_with_controls(
    controls_by_state: dict[int, list[ControlRecord]],
    termination_reason: str | None = None,
    has_iframes_states: set[int] | None = None,
) -> Graph:
    """Build a graph where each key in controls_by_state becomes a state at that depth."""
    g = Graph()
    iframes = has_iframes_states or set()
    for depth, controls in sorted(controls_by_state.items()):
        state = g.add_state(
            url=f"https://example.com/page{depth}",
            fingerprint_hash=f"fp{depth}",
            title=f"Page {depth}",
            depth=depth,
        )
        state.controls = controls
        state.has_iframes = depth in iframes
    g.termination_reason = termination_reason
    return g


# ---------------------------------------------------------------------------
# test_every_discovered_action_has_outcome
# ---------------------------------------------------------------------------


def test_every_discovered_action_has_outcome():
    """When every control has an outcome, 'unset' does not appear in the report."""
    g = _build_graph_with_controls(
        {
            0: [
                _make_control(text="Link A", outcome="explored", target_state_id="s1"),
                _make_control(text="Link B", outcome="no_change"),
            ],
            1: [
                _make_control(text="Link C", outcome="existing_state"),
                _make_control(text="Link D", outcome="out_of_scope"),
            ],
        }
    )
    report = generate_report(g)
    assert "unset" not in report


# ---------------------------------------------------------------------------
# test_limits_and_failures_mark_coverage_partial
# ---------------------------------------------------------------------------


def test_limits_and_failures_mark_coverage_partial():
    """Budget exceeded or max_states termination marks coverage as PARTIAL."""
    g = _build_graph_with_controls(
        {
            0: [
                _make_control(text="Link A", outcome="explored"),
                _make_control(text="Link B", outcome="budget_exceeded"),
            ],
        },
        termination_reason="max_states",
    )
    report = generate_report(g)
    assert "PARTIAL" in report


# ---------------------------------------------------------------------------
# test_blocked_workflow_is_not_reported_as_explored
# ---------------------------------------------------------------------------


def test_blocked_workflow_is_not_reported_as_explored():
    """Unsafe-skipped controls appear with their reasons; are not counted as explored."""
    g = _build_graph_with_controls(
        {
            0: [
                _make_control(
                    text="Delete All",
                    outcome="unsafe_skipped",
                    unsafe_reason="matched text pattern: (?i)delete",
                    is_safe=False,
                ),
                _make_control(
                    text="Save Changes",
                    outcome="unsafe_skipped",
                    unsafe_reason="matched text pattern: (?i)save",
                    is_safe=False,
                ),
                _make_control(text="View Page", outcome="explored"),
            ],
        }
    )
    report = generate_report(g)

    # Unsafe controls are listed with their reasons
    assert "unsafe_skipped" in report
    assert "(?i)delete" in report
    assert "(?i)save" in report

    # The summary counts: 2 unsafe, 1 explored
    assert "Unsafe (skipped):       2" in report
    assert "Explored" in report


# ---------------------------------------------------------------------------
# test_frontier_exhausted_with_iframes
# ---------------------------------------------------------------------------


def test_frontier_exhausted_with_iframes():
    """Frontier-exhausted + iframes -> report mentions iframes in coverage."""
    g = _build_graph_with_controls(
        {
            0: [
                _make_control(text="Link", outcome="explored"),
            ],
        },
        termination_reason="frontier_exhausted",
        has_iframes_states={0},
    )
    report = generate_report(g)

    # Coverage mentions iframes
    assert "iframe" in report.lower()
    # The per-state detail also flags iframes
    assert "Contains iframes" in report


# ---------------------------------------------------------------------------
# test_report_writes_to_file
# ---------------------------------------------------------------------------


def test_report_writes_to_file(tmp_path):
    """generate_report with output_path writes the report to disk."""
    g = _build_graph_with_controls(
        {
            0: [_make_control(text="Link", outcome="explored")],
        }
    )
    out = tmp_path / "report.txt"
    report_text = generate_report(g, output_path=out)

    assert out.exists()
    file_content = out.read_text()
    assert file_content == report_text
    assert "AutoSiteMap Exploration Report" in file_content
