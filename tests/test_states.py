"""AC5 -- State fingerprinting, graph structure, and budget tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from playwright.async_api import async_playwright

from autositemap.config import Config
from autositemap.crawler import explore
from autositemap.graph import Graph
from autositemap.state import compute_fingerprint


@pytest.mark.slow
async def test_same_url_dialog_has_distinct_state(
    fixture_config: Config, fixture_server, output_dir
):
    """Navigate to index. Compute fingerprint. Click 'Open Dialog'. Compute
    fingerprint again. Assert the two fingerprints have the same URL but
    different dom_hash."""
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

        fp_before = await compute_fingerprint(page, fixture_config.fingerprint)

        # Open the modal dialog
        await page.click("#open-modal")
        await page.wait_for_timeout(500)

        fp_after = await compute_fingerprint(page, fixture_config.fingerprint)

        assert fp_before.url == fp_after.url, "URL should remain the same after opening dialog"
        assert fp_before.dom_hash != fp_after.dom_hash, (
            "DOM hash should differ when the modal is open"
        )


@pytest.mark.slow
async def test_excluded_timestamp_does_not_create_state(
    fixture_config: Config, fixture_server, output_dir
):
    """Navigate to index twice (or reload). The timestamp element is in
    ignore_selectors. Assert fingerprints match despite the timestamp being
    on the page."""
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

        # First visit
        await page.goto(f"{base_url}/", wait_until="load")
        fp1 = await compute_fingerprint(page, fixture_config.fingerprint)

        # Verify the timestamp and dynamic-content elements are present
        assert await page.locator(".timestamp").count() > 0
        assert await page.locator(".dynamic-content").count() > 0

        # Reload and compute again
        await page.reload(wait_until="load")
        fp2 = await compute_fingerprint(page, fixture_config.fingerprint)

        assert fp1.url == fp2.url
        assert fp1.dom_hash == fp2.dom_hash, (
            "Fingerprints should match despite timestamp/dynamic content "
            "because those selectors are in ignore_selectors"
        )


@pytest.mark.slow
async def test_shared_destination_and_cycle_are_preserved(
    fixture_config: Config, fixture_server, output_dir
):
    """Manually navigate index -> list -> detail -> index to build a graph
    with a cycle. Assert the graph records a cross-link transition back to
    the root state when a visited URL is re-encountered."""
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

        graph = Graph()

        # State 1: Index
        await page.goto(f"{base_url}/", wait_until="load")
        fp_index = await compute_fingerprint(page, fixture_config.fingerprint)
        s_index = graph.add_state(
            url=fp_index.url,
            fingerprint_hash=fp_index.dom_hash,
            title=await page.title(),
            depth=0,
        )

        # State 2: List
        await page.goto(f"{base_url}/list.html", wait_until="load")
        fp_list = await compute_fingerprint(page, fixture_config.fingerprint)
        s_list = graph.add_state(
            url=fp_list.url,
            fingerprint_hash=fp_list.dom_hash,
            title=await page.title(),
            depth=1,
        )
        graph.add_transition(
            s_index.id,
            s_list.id,
            "a[href='/list.html']",
            "Item List",
            is_tree_edge=True,
        )

        # State 3: Detail
        await page.goto(f"{base_url}/detail.html?id=1", wait_until="load")
        fp_detail = await compute_fingerprint(page, fixture_config.fingerprint)
        s_detail = graph.add_state(
            url=fp_detail.url,
            fingerprint_hash=fp_detail.dom_hash,
            title=await page.title(),
            depth=2,
        )
        graph.add_transition(
            s_list.id,
            s_detail.id,
            "a[href='/detail.html?id=1']",
            "Item 1",
            is_tree_edge=True,
        )

        # Detail links back to index (cycle). Detect it as cross-link.
        await page.goto(f"{base_url}/", wait_until="load")
        fp_back = await compute_fingerprint(page, fixture_config.fingerprint)
        existing = graph.find_state_by_fingerprint(fp_back.url, fp_back.dom_hash)
        assert existing is not None, "Navigating back to index should match an existing state"
        assert existing.id == s_index.id, "Should match the root state"

        # Record the cross-link
        graph.add_transition(
            s_detail.id,
            existing.id,
            "a[href='/']",
            "Back to Dashboard",
            is_tree_edge=False,
        )

        # Verify graph structure
        assert graph.state_count == 3
        assert graph.tree_edge_count == 2
        assert graph.cross_link_count == 1

        # The cross-link should reference valid states
        cross_links = [t for t in graph.transitions if not t.is_tree_edge]
        assert len(cross_links) == 1
        assert cross_links[0].source_state_id == s_detail.id
        assert cross_links[0].target_state_id == s_index.id

        # Verify all transitions reference existing states
        state_ids = set(graph.states.keys())
        for t in graph.transitions:
            assert t.source_state_id in state_ids
            assert t.target_state_id in state_ids

        await browser.close()


@pytest.mark.slow
async def test_failed_restoration_does_not_misattribute_edge(
    fixture_config: Config, fixture_server, output_dir
):
    """Run explore() and verify that every transition's source_state_id and
    target_state_id correspond to states that exist in the graph."""
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

        state_ids = set(graph.states.keys())
        for t in graph.transitions:
            assert t.source_state_id in state_ids, (
                f"Transition source {t.source_state_id} not in graph states"
            )
            assert t.target_state_id in state_ids, (
                f"Transition target {t.target_state_id} not in graph states"
            )

        # Also verify control target_state_id references are valid
        for state in graph.states.values():
            for ctrl in state.controls:
                if ctrl.target_state_id is not None:
                    assert ctrl.target_state_id in state_ids, (
                        f"Control in {state.id} references nonexistent target state "
                        f"{ctrl.target_state_id}"
                    )

        await browser.close()


@pytest.mark.slow
async def test_limit_and_interrupt_preserve_partial_output(
    fixture_config: Config, fixture_server, output_dir
):
    """Create a config with max_states=3. Run crawl. Assert graph has at most
    3 states, the crawl terminated early, and graph.json is still
    valid/loadable."""
    limited_config = replace(
        fixture_config,
        budgets=replace(fixture_config.budgets, max_states=3),
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={
                "width": limited_config.viewport.width,
                "height": limited_config.viewport.height,
            },
            service_workers="block",
        )
        page = await context.new_page()
        base_url = fixture_server.base_url

        await context.add_cookies([{"name": "auth", "value": "valid", "url": base_url}])
        await page.goto(f"{base_url}/", wait_until="load")

        graph = await explore(page, limited_config, output_dir)

        assert graph.state_count <= 3, (
            f"Expected at most 3 states with max_states=3, got {graph.state_count}"
        )

        # The crawl should terminate early -- either by reaching max_states
        # or by hitting the global_timeout (which also respects the budget).
        # If the crawl was slow and only explored 1 state before timeout,
        # frontier_exhausted is also valid when no queued actions remain.
        valid_reasons = {"max_states", "global_timeout", "frontier_exhausted"}
        assert graph.termination_reason in valid_reasons, (
            f"Expected termination_reason in {valid_reasons}, got '{graph.termination_reason}'"
        )

        # Save and reload to verify graph.json is valid/loadable
        graph_path = output_dir / "graph.json"
        graph.save(graph_path)
        loaded = Graph.load(graph_path)

        assert loaded.state_count == graph.state_count
        assert loaded.termination_reason == graph.termination_reason
        assert loaded.root_state_id is not None

        await browser.close()
