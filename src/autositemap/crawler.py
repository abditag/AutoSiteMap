from __future__ import annotations

import contextlib
import re
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import Page

from autositemap.config import Config
from autositemap.graph import Graph
from autositemap.safety import (
    check_form_context,
    check_session_expired,
    check_unsafe_selectors,
    detect_iframes,
    discover_controls,
    install_dialog_handler,
    install_scope_guards,
    is_url_in_scope,
    post_click_scope_check,
)
from autositemap.screenshot import capture_screenshot
from autositemap.state import StateFingerprint, compute_fingerprint

ReplayPath = list[tuple[str, str]]


async def explore(
    page: Page,
    config: Config,
    output_dir: Path,
    graph: Graph | None = None,
) -> Graph:
    if graph is None:
        graph = Graph(
            config_path=config.config_path,
            started_at=datetime.now(UTC).isoformat(),
        )
    else:
        graph.config_path = config.config_path
        graph.started_at = datetime.now(UTC).isoformat()
    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    await install_scope_guards(page.context, config, graph)
    await install_dialog_handler(page)

    start_time = time.monotonic()

    queue: deque[tuple[str, ReplayPath]] = deque()
    visited_actions: set[tuple[str, str]] = set()
    state_fingerprints: dict[str, StateFingerprint] = {}

    fp = await compute_fingerprint(page, config.fingerprint)
    title = await _get_title(page)
    root = graph.add_state(url=fp.url, fingerprint_hash=fp.dom_hash, title=title, depth=0)
    state_fingerprints[root.id] = fp

    root.has_iframes = await detect_iframes(page)

    try:
        orig, deriv = await capture_screenshot(page, root.id, config, screenshots_dir)
        root.screenshot_filename = orig
        root.screenshot_derivative = deriv
    except Exception as e:
        print(f"  Screenshot failed for {root.id}: {e}")

    controls = await discover_controls(page, config, page.url)
    await _apply_unsafe_selectors(page, controls, config)
    root.controls = controls

    for ctrl in controls:
        if ctrl.is_safe and ctrl.outcome is None:
            queue.append((root.id, [(root.id, ctrl.selector)]))

    try:
        while queue:
            if _check_global_timeout(start_time, config):
                graph.termination_reason = "global_timeout"
                break

            if graph.state_count >= config.budgets.max_states:
                graph.termination_reason = "max_states"
                break

            _source_state_id, replay_path = queue.popleft()
            state_id, selector = replay_path[-1]

            if (state_id, selector) in visited_actions:
                continue
            visited_actions.add((state_id, selector))

            depth = len(replay_path)
            if depth > config.budgets.max_depth:
                _mark_control_outcome(graph, state_id, selector, "budget_exceeded")
                continue

            actions_on_state = sum(1 for k in visited_actions if k[0] == state_id)
            if actions_on_state > config.budgets.max_actions_per_state:
                _mark_control_outcome(graph, state_id, selector, "budget_exceeded")
                continue

            restored = await _restore_state(
                page,
                graph,
                config,
                state_fingerprints,
                state_id,
                replay_path,
                start_time,
            )
            if not restored:
                _mark_control_outcome(graph, state_id, selector, "restore_failed")
                continue

            outcome = await _execute_action(
                page,
                graph,
                config,
                screenshots_dir,
                state_id,
                selector,
                depth,
                state_fingerprints,
                queue,
                replay_path,
                start_time,
                visited_actions,
            )

            if outcome:
                _mark_control_outcome(graph, state_id, selector, outcome)

    except KeyboardInterrupt:
        graph.termination_reason = "interrupted"
        print("\n⚠  Interrupted. Saving partial results.")

    if graph.termination_reason is None:
        graph.termination_reason = "frontier_exhausted"

    _mark_remaining_unexplored(graph, visited_actions)
    graph.finished_at = datetime.now(UTC).isoformat()
    return graph


async def _restore_state(
    page: Page,
    graph: Graph,
    config: Config,
    state_fingerprints: dict[str, StateFingerprint],
    target_state_id: str,
    replay_path: ReplayPath,
    start_time: float,
) -> bool:
    target_fp = state_fingerprints.get(target_state_id)
    if not target_fp:
        return False

    current_fp = await compute_fingerprint(page, config.fingerprint)
    if current_fp.matches(target_fp):
        return True

    shortcut_idx = _find_shortcut(current_fp, replay_path, state_fingerprints)

    steps_to_replay = replay_path[:-1]
    if shortcut_idx is not None:
        steps_to_replay = replay_path[shortcut_idx:-1]
    else:
        target_state = graph.states.get(target_state_id)
        if not target_state:
            return False
        try:
            await page.goto(
                config.site.start_url,
                wait_until="load",
                timeout=config.budgets.action_timeout * 1000,
            )
        except Exception:
            return False

    for step_state_id, step_selector in steps_to_replay:
        if _check_global_timeout(start_time, config):
            return False

        expected_fp = state_fingerprints.get(step_state_id)
        if expected_fp and shortcut_idx is None:
            current = await compute_fingerprint(page, config.fingerprint)
            if not current.matches(expected_fp):
                return False

        try:
            await page.click(step_selector, timeout=config.budgets.action_timeout * 1000)
            await page.wait_for_load_state("load", timeout=3000)
            await page.wait_for_timeout(500)
        except Exception:
            return False

    current_fp = await compute_fingerprint(page, config.fingerprint)
    return current_fp.matches(target_fp)


def _find_shortcut(
    current_fp: StateFingerprint,
    replay_path: ReplayPath,
    state_fingerprints: dict[str, StateFingerprint],
) -> int | None:
    for i, (sid, _) in enumerate(replay_path[:-1]):
        fp = state_fingerprints.get(sid)
        if fp and current_fp.matches(fp):
            return i
    return None


async def _execute_action(
    page: Page,
    graph: Graph,
    config: Config,
    screenshots_dir: Path,
    source_state_id: str,
    selector: str,
    depth: int,
    state_fingerprints: dict[str, StateFingerprint],
    queue: deque,
    replay_path: ReplayPath,
    start_time: float,
    visited_actions: set[tuple[str, str]],
) -> str | None:
    source_fp = state_fingerprints.get(source_state_id)
    if not source_fp:
        return "error"

    try:
        await _try_dismiss_overlays(page, config, selector)
        await page.click(selector, timeout=config.budgets.action_timeout * 1000)
    except Exception as e:
        _mark_control_error(graph, source_state_id, selector, str(e))
        return "error"

    with contextlib.suppress(Exception):
        await page.wait_for_load_state("load", timeout=3000)
    await page.wait_for_timeout(500)

    escaped_url = await post_click_scope_check(page, config)
    if escaped_url:
        ctrl = _find_control(graph, source_state_id, selector)
        if ctrl:
            ctrl.destination_url = escaped_url
        graph.add_out_of_scope(source_state_id, escaped_url, ctrl.text if ctrl else "")
        with contextlib.suppress(Exception):
            await page.goto(
                config.site.start_url,
                wait_until="load",
                timeout=config.budgets.action_timeout * 1000,
            )
        return "out_of_scope"

    if await check_session_expired(page, config):
        return "session_expired"

    new_fp = await compute_fingerprint(page, config.fingerprint)

    if source_fp.matches(new_fp):
        return "no_change"

    existing = graph.find_state_by_fingerprint(new_fp.url, new_fp.dom_hash)
    if existing:
        ctrl = _find_control(graph, source_state_id, selector)
        ctrl_text = ctrl.text if ctrl else ""
        if ctrl:
            ctrl.target_state_id = existing.id
            ctrl.outcome = "explored"
        graph.add_transition(source_state_id, existing.id, selector, ctrl_text, is_tree_edge=False)
        return None

    if graph.state_count >= config.budgets.max_states:
        return "budget_exceeded"

    title = await _get_title(page)
    new_state = graph.add_state(
        url=new_fp.url, fingerprint_hash=new_fp.dom_hash, title=title, depth=depth
    )
    state_fingerprints[new_state.id] = new_fp

    new_state.has_iframes = await detect_iframes(page)

    try:
        orig, deriv = await capture_screenshot(page, new_state.id, config, screenshots_dir)
        new_state.screenshot_filename = orig
        new_state.screenshot_derivative = deriv
    except Exception as e:
        print(f"  Screenshot failed for {new_state.id}: {e}")

    ctrl = _find_control(graph, source_state_id, selector)
    ctrl_text = ctrl.text if ctrl else ""
    if ctrl:
        ctrl.target_state_id = new_state.id
        ctrl.outcome = "explored"

    graph.add_transition(source_state_id, new_state.id, selector, ctrl_text, is_tree_edge=True)

    new_controls = await discover_controls(page, config, page.url)
    await _apply_unsafe_selectors(page, new_controls, config)
    new_state.controls = new_controls

    for nc in new_controls:
        if (
            nc.is_safe
            and nc.outcome is None
            and (new_state.id, nc.selector) not in visited_actions
        ):
            new_path = [*replay_path, (new_state.id, nc.selector)]
            queue.append((new_state.id, new_path))

    return None


async def _apply_unsafe_selectors(page, controls, config):
    for ctrl in controls:
        if not ctrl.is_safe:
            continue
        reason = await check_unsafe_selectors(page, ctrl.selector, config)
        if reason:
            ctrl.is_safe = False
            ctrl.unsafe_reason = reason
            ctrl.outcome = "unsafe_skipped"
            continue
        reason = await check_form_context(page, ctrl.selector)
        if reason:
            ctrl.is_safe = False
            ctrl.unsafe_reason = reason
            ctrl.outcome = "unsafe_skipped"


async def _try_dismiss_overlays(page: Page, config: Config, target_selector: str) -> None:
    try:
        target = page.locator(target_selector)
        if await target.is_visible():
            return
    except Exception:
        pass

    for sel in config.controls.dismiss_selectors:
        try:
            loc = page.locator(sel)
            if not await loc.is_visible():
                continue
            reason = await check_unsafe_selectors(page, sel, config)
            if reason:
                continue
            reason = await check_form_context(page, sel)
            if reason:
                continue
            el_text = await loc.inner_text()
            el_aria = await loc.get_attribute("aria-label")
            blocked = False
            for pattern in config.controls.unsafe_text_patterns:
                for label in (el_text, el_aria):
                    if label and re.search(pattern, label):
                        blocked = True
                        break
                if blocked:
                    break
            if blocked:
                continue
            el_href = await loc.get_attribute("href")
            if el_href:
                resolved = _resolve_dismiss_href(el_href, page.url)
                if resolved and not is_url_in_scope(resolved, config):
                    continue
            await loc.click(timeout=1000)
            await page.wait_for_timeout(300)
            return
        except Exception:
            continue
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
    except Exception:
        pass


def _check_global_timeout(start_time: float, config: Config) -> bool:
    return (time.monotonic() - start_time) > config.budgets.global_timeout


def _mark_control_outcome(graph: Graph, state_id: str, selector: str, outcome: str) -> None:
    ctrl = _find_control(graph, state_id, selector)
    if ctrl and ctrl.outcome is None:
        ctrl.outcome = outcome


def _mark_control_error(graph: Graph, state_id: str, selector: str, message: str) -> None:
    ctrl = _find_control(graph, state_id, selector)
    if ctrl:
        ctrl.outcome = "error"
        ctrl.error_message = message


def _find_control(graph: Graph, state_id: str, selector: str):
    state = graph.states.get(state_id)
    if not state:
        return None
    for ctrl in state.controls:
        if ctrl.selector == selector:
            return ctrl
    return None


def _resolve_dismiss_href(href: str, page_url: str) -> str | None:
    if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
        return None
    return urljoin(page_url, href)


def _mark_remaining_unexplored(graph: Graph, visited_actions: set[tuple[str, str]]) -> None:
    for state in graph.states.values():
        for ctrl in state.controls:
            if (
                ctrl.outcome is None
                and ctrl.is_safe
                and (state.id, ctrl.selector) not in visited_actions
            ):
                ctrl.outcome = "not_explored"


async def _get_title(page: Page) -> str:
    try:
        return await page.title()
    except Exception:
        return ""
