from __future__ import annotations

from pathlib import Path

from autositemap.graph import Graph


def generate_report(graph: Graph, output_path: Path | None = None) -> str:
    lines: list[str] = []
    _h = lines.append

    _h("AutoSiteMap Exploration Report")
    _h("=" * 60)
    _h(f"Config: {graph.config_path or 'N/A'}")
    _h(f"Started: {graph.started_at or 'N/A'}")
    _h(f"Finished: {graph.finished_at or 'N/A'}")
    _h(f"Termination: {graph.termination_reason or 'N/A'}")
    _h("")

    _h(f"States Discovered: {graph.state_count}")
    _h(
        f"Transitions Recorded: {graph.transition_count} "
        f"({graph.tree_edge_count} tree edges, {graph.cross_link_count} cross-links)"
    )
    _h(f"Out-of-Scope URLs: {len(graph.out_of_scope_urls)}")
    _h("")

    total = 0
    explored = 0
    no_change = 0
    existing = 0
    unsafe = 0
    disabled = 0
    download = 0
    out_of_scope = 0
    budget = 0
    not_explored = 0
    errors = 0
    restore_failed = 0
    other = 0

    for state in graph.states.values():
        for ctrl in state.controls:
            total += 1
            match ctrl.outcome:
                case "explored":
                    explored += 1
                case "no_change":
                    no_change += 1
                case "existing_state":
                    existing += 1
                case "unsafe_skipped":
                    unsafe += 1
                case "disabled":
                    disabled += 1
                case "download_skipped":
                    download += 1
                case "out_of_scope":
                    out_of_scope += 1
                case "budget_exceeded":
                    budget += 1
                case "not_explored":
                    not_explored += 1
                case "error":
                    errors += 1
                case "restore_failed":
                    restore_failed += 1
                case _:
                    other += 1

    _h("Controls Summary")
    _h("-" * 40)
    _h(f"  Total discovered:       {total}")
    _h(f"  Explored → new state:   {explored}")
    _h(f"  Explored → no change:   {no_change}")
    _h(f"  Explored → existing:    {existing}")
    _h(f"  Unsafe (skipped):       {unsafe}")
    _h(f"  Disabled:               {disabled}")
    _h(f"  Download (skipped):     {download}")
    _h(f"  Out of scope:           {out_of_scope}")
    _h(f"  Budget exceeded:        {budget}")
    _h(f"  Not explored:           {not_explored}")
    _h(f"  Restore failed:         {restore_failed}")
    _h(f"  Errors:                 {errors}")
    if other:
        _h(f"  Other/unset:            {other}")
    _h("")

    coverage = (
        "PARTIAL"
        if (
            budget
            or not_explored
            or restore_failed
            or graph.termination_reason not in ("frontier_exhausted", None)
        )
        else "COMPLETE (within discovered states)"
    )

    has_iframes = any(s.has_iframes for s in graph.states.values())
    if has_iframes:
        coverage += " — iframes present but not entered"

    _h(f"Coverage Assessment: {coverage}")
    _h("")

    _h("Per-State Detail")
    _h("=" * 60)

    for state_id in sorted(graph.states.keys(), key=lambda s: int(s[1:])):
        state = graph.states[state_id]
        _h(f"\n  {state_id}: {state.title or '(untitled)'}")
        _h(f"    URL: {state.url}")
        _h(f"    Screenshot: {state.screenshot_filename or 'MISSING'}")
        _h(f"    Depth: {state.depth}")
        if state.has_iframes:
            _h("    ⚠ Contains iframes (not entered)")
        _h(f"    Controls: {len(state.controls)}")

        for ctrl in state.controls:
            outcome_str = ctrl.outcome or "unset"
            target = ""
            if ctrl.target_state_id:
                target = f" → {ctrl.target_state_id}"
            if ctrl.destination_url:
                target = f" → {ctrl.destination_url}"
            reason = ""
            if ctrl.unsafe_reason:
                reason = f" (reason: {ctrl.unsafe_reason})"
            if ctrl.error_message:
                reason = f" (error: {ctrl.error_message[:60]})"

            label = ctrl.text[:40] if ctrl.text else ctrl.selector[:40]
            _h(f'      [{outcome_str}{target}] {ctrl.tag} "{label}"{reason}')

    if graph.out_of_scope_urls:
        _h("\n\nOut-of-Scope Destinations")
        _h("-" * 40)
        for oos in graph.out_of_scope_urls:
            _h(f"  From {oos['source_state_id']}: {oos['url']}")

    _h("")
    report = "\n".join(lines)

    if output_path:
        output_path.write_text(report)

    return report
