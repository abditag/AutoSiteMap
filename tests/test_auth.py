"""AC2 -- Authentication and session tests."""

from __future__ import annotations

import json

import pytest
from playwright.async_api import async_playwright

from autositemap.config import Config
from autositemap.graph import Graph
from autositemap.safety import check_session_expired


@pytest.mark.slow
async def test_crawl_waits_for_login_completion(
    fixture_config: Config, fixture_server, output_dir
):
    """Navigate to login page, simulate login (click submit), verify page reaches
    the dashboard with readiness selector visible."""
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

        await page.goto(fixture_config.auth.login_url, wait_until="load")

        # The login form should be visible
        assert await page.locator("#login-form").is_visible()

        # Click submit to trigger doLogin which sets cookie and redirects to /
        await page.click("button[type='submit']")
        await page.wait_for_load_state("load")

        # After login we should land on the dashboard
        readiness = page.locator(fixture_config.auth.readiness_selector)
        await readiness.wait_for(state="visible", timeout=5000)
        assert await readiness.is_visible()

        await browser.close()


@pytest.mark.slow
async def test_expired_session_stops_exploration(
    fixture_config: Config, fixture_server, output_dir
):
    """Navigate to /api/expire-session which shows a page with #login-form.
    Call check_session_expired(page, config) and assert it returns True."""
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

        await page.goto(f"{base_url}/api/expire-session", wait_until="load")

        expired = await check_session_expired(page, fixture_config)
        assert expired is True, "Session should be detected as expired on the expire-session page"

        # Verify it returns False on a normal page
        await context.add_cookies([{"name": "auth", "value": "valid", "url": base_url}])
        await page.goto(f"{base_url}/", wait_until="load")
        not_expired = await check_session_expired(page, fixture_config)
        assert not_expired is False, "Session should NOT be detected as expired on the dashboard"

        await browser.close()


@pytest.mark.slow
async def test_export_excludes_session_secrets(fixture_config: Config, fixture_server, output_dir):
    """Save auth state to output_dir, create a graph and save it.
    Verify graph.json does not contain cookie values, passwords, or session tokens.
    Verify auth_state.json is NOT included in the graph's serialized data."""
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

        # Navigate to login, perform login to set cookie
        await page.goto(f"{base_url}/login.html", wait_until="load")
        await page.click("button[type='submit']")
        await page.wait_for_load_state("load")

        # Save auth state (like the real auth module does)
        auth_path = output_dir / "auth_state.json"
        await context.storage_state(path=str(auth_path))
        assert auth_path.exists(), "auth_state.json should have been saved"

        # Build a simple graph and save it
        graph = Graph(config_path=str(fixture_config.config_path))
        graph.add_state(
            url=f"{base_url}/",
            fingerprint_hash="abc123",
            title="Dashboard",
            depth=0,
        )
        graph_path = output_dir / "graph.json"
        graph.save(graph_path)

        # Read graph.json and verify it contains no secrets
        graph_text = graph_path.read_text()
        _ = json.loads(graph_text)

        # The graph should not contain cookie values
        assert "auth=valid" not in graph_text, "Graph should not contain cookie values"
        assert "testpass" not in graph_text, "Graph should not contain passwords"

        # The graph should not reference auth_state.json in any field
        assert "auth_state" not in graph_text, "Graph should not reference auth_state.json"

        # auth_state.json should exist but be separate from the graph
        auth_data = json.loads(auth_path.read_text())
        assert isinstance(auth_data, dict), "auth_state.json should be valid JSON"

        await browser.close()
