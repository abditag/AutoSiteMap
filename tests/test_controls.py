"""AC4 -- Control discovery and safety classification tests."""

from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from autositemap.config import Config
from autositemap.crawler import explore
from autositemap.safety import discover_controls, is_url_in_scope


@pytest.mark.slow
async def test_safe_dialog_and_tab_are_explored(
    fixture_config: Config, fixture_server, output_dir
):
    """Navigate to index. Discover controls. Find the 'Open Dialog' button and
    tab buttons. Assert they are classified as safe."""
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

        controls = await discover_controls(page, fixture_config, page.url)

        # Find the Open Dialog button
        modal_btns = [c for c in controls if "Open Dialog" in c.text]
        assert len(modal_btns) >= 1, "Should discover the 'Open Dialog' button"
        modal_btn = modal_btns[0]
        assert modal_btn.is_safe is True, "Open Dialog button should be safe"
        assert modal_btn.control_type == "button"

        # Find tab buttons
        tab_controls = [c for c in controls if c.role == "tab"]
        assert len(tab_controls) >= 2, "Should discover at least 2 tab buttons"
        for tab in tab_controls:
            assert tab.is_safe is True, f"Tab '{tab.text}' should be safe"
            assert tab.control_type == "tab"

        await browser.close()


@pytest.mark.slow
async def test_unknown_and_mutating_controls_are_not_clicked(
    fixture_config: Config, fixture_server, output_dir, clean_mutations
):
    """Run a full explore() crawl on the fixture site. Verify the Delete button
    is classified as unsafe_skipped and the mutation log stays empty."""
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

        # First, verify the Delete button classification directly on the
        # detail page. This does not depend on crawl ordering or timeouts.
        await page.goto(f"{base_url}/detail.html?id=1", wait_until="load")
        detail_controls = await discover_controls(page, fixture_config, page.url)
        delete_ctrls = [c for c in detail_controls if "Delete" in (c.text or "")]
        assert len(delete_ctrls) >= 1, "Should discover the 'Delete Item' control"
        for ctrl in delete_ctrls:
            assert ctrl.outcome == "unsafe_skipped", (
                f"Delete control should be unsafe_skipped, got: {ctrl.outcome}"
            )

        # Now run the full crawl from the start page to verify the crawler
        # does not trigger any mutations (POSTs to the fixture server).
        await page.goto(f"{base_url}/", wait_until="load")
        graph = await explore(page, fixture_config, output_dir)

        # If the crawl reached the detail page, verify the Delete button
        # in the graph also has the right outcome.
        for state in graph.states.values():
            for ctrl in state.controls:
                if "Delete" in (ctrl.text or ""):
                    assert ctrl.outcome == "unsafe_skipped"

        # Mutation log should be empty (verified by clean_mutations fixture on teardown)

        await browser.close()


@pytest.mark.slow
async def test_deny_rule_overrides_allow_rule(fixture_config: Config, fixture_server, output_dir):
    """Discover controls on index page. The /admin/panel.html link should match
    the deny pattern and be marked out_of_scope or unsafe."""
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

        controls = await discover_controls(page, fixture_config, page.url)

        admin_controls = [c for c in controls if c.href and "/admin" in c.href]
        assert len(admin_controls) >= 1, "Should discover the admin link"
        admin_ctrl = admin_controls[0]

        # The admin URL matches the deny pattern in is_url_in_scope, so
        # _classify_safety returns is_safe=False with reason "out_of_scope".
        # discover_controls then assigns outcome="unsafe_skipped" for any
        # control where is_safe is already False from classification.
        assert admin_ctrl.is_safe is False
        assert admin_ctrl.unsafe_reason == "out_of_scope", (
            f"Admin link unsafe_reason should be 'out_of_scope', got: {admin_ctrl.unsafe_reason!r}"
        )
        assert admin_ctrl.outcome == "unsafe_skipped", (
            f"Admin link outcome should be 'unsafe_skipped', got: {admin_ctrl.outcome!r}"
        )

        # Verify directly with is_url_in_scope
        assert is_url_in_scope(admin_ctrl.href, fixture_config) is False

        await browser.close()


@pytest.mark.slow
async def test_disabled_download_and_no_change_outcomes(
    fixture_config: Config, fixture_server, output_dir
):
    """Discover controls on index page. The disabled button should have
    outcome='disabled'. The download link should have outcome='download_skipped'."""
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

        controls = await discover_controls(page, fixture_config, page.url)

        # Find the disabled button
        disabled_controls = [c for c in controls if "Disabled" in (c.text or "")]
        assert len(disabled_controls) >= 1, "Should discover the disabled button"
        disabled_ctrl = disabled_controls[0]
        assert disabled_ctrl.outcome == "disabled", (
            f"Disabled button should have outcome='disabled', got: {disabled_ctrl.outcome}"
        )
        assert disabled_ctrl.is_safe is False

        # Find the download link
        download_controls = [c for c in controls if "Download" in (c.text or "")]
        assert len(download_controls) >= 1, "Should discover the download link"
        download_ctrl = download_controls[0]
        assert download_ctrl.outcome == "download_skipped", (
            f"Download link should have outcome='download_skipped', got: {download_ctrl.outcome}"
        )
        assert download_ctrl.is_safe is False

        await browser.close()
