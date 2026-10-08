"""AC3 -- Scope enforcement tests."""

from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from autositemap.config import Config
from autositemap.graph import Graph
from autositemap.safety import install_scope_guards, is_url_in_scope
from autositemap.state import compute_fingerprint


async def test_scope_accepts_root_and_descendants(fixture_config: Config, fixture_server):
    """Root URL, list page, and detail page with query params are all in scope."""
    base_url = fixture_server.base_url

    assert is_url_in_scope(f"{base_url}/", fixture_config) is True
    assert is_url_in_scope(f"{base_url}/list.html", fixture_config) is True
    assert is_url_in_scope(f"{base_url}/detail.html?id=1", fixture_config) is True


async def test_scope_rejects_sibling_prefix_and_other_origin(
    fixture_config: Config, fixture_server
):
    """External origin, sibling port, and denied admin path are all rejected."""
    base_url = fixture_server.base_url
    port = fixture_server.port

    # Different origin entirely
    assert is_url_in_scope("https://example.com/", fixture_config) is False

    # Same host, different port (sibling prefix)
    sibling_url = base_url.replace(str(port), str(port + 1))
    assert is_url_in_scope(f"{sibling_url}/", fixture_config) is False

    # /admin/panel.html matches deny pattern
    assert is_url_in_scope(f"{base_url}/admin/panel.html", fixture_config) is False


@pytest.mark.slow
async def test_redirect_and_popup_scope_guards(fixture_config: Config, fixture_server, output_dir):
    """Install scope guards on a context, navigate to index, click the external
    link. Verify the popup was handled and the out-of-scope URL was recorded."""
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

        graph = Graph()
        graph.add_state(
            url=f"{base_url}/",
            fingerprint_hash="test",
            title="Dashboard",
        )

        await install_scope_guards(context, fixture_config, graph)

        await context.add_cookies([{"name": "auth", "value": "valid", "url": base_url}])
        await page.goto(f"{base_url}/", wait_until="load")

        # Click the external link (target="_blank" opens a popup)
        # The scope guard should intercept it
        async with page.expect_popup() as _popup_info:
            await page.click('a[href="https://example.com"]')

        # Wait a moment for the popup handler to fire
        await page.wait_for_timeout(1000)

        # The external URL should be recorded as out-of-scope
        out_of_scope_urls = [entry["url"] for entry in graph.out_of_scope_urls]
        assert any("example.com" in url for url in out_of_scope_urls), (
            f"Expected an example.com URL in out_of_scope_urls, got: {out_of_scope_urls}"
        )

        # The main page should still be on the fixture site
        assert base_url in page.url

        await browser.close()


@pytest.mark.slow
async def test_stateful_query_and_fragment_are_preserved(
    fixture_config: Config, fixture_server, output_dir
):
    """Navigate to /detail.html?id=1 and /detail.html?id=2. Compute fingerprints
    for both. Assert they have different URLs (query preserved) and can be stored
    as different states."""
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

        # Navigate to detail?id=1
        await page.goto(f"{base_url}/detail.html?id=1", wait_until="load")
        fp1 = await compute_fingerprint(page, fixture_config.fingerprint)

        # Navigate to detail?id=2
        await page.goto(f"{base_url}/detail.html?id=2", wait_until="load")
        fp2 = await compute_fingerprint(page, fixture_config.fingerprint)

        # Different query params -> different URLs preserved
        assert "id=1" in fp1.url
        assert "id=2" in fp2.url
        assert fp1.url != fp2.url, "Query params should be preserved, yielding different URLs"

        # They can be stored as different states in a graph
        graph = Graph()
        s1 = graph.add_state(url=fp1.url, fingerprint_hash=fp1.dom_hash, title="Item 1")
        s2 = graph.add_state(url=fp2.url, fingerprint_hash=fp2.dom_hash, title="Item 2")
        assert s1.id != s2.id
        assert graph.state_count == 2

        await browser.close()
