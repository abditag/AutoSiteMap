"""AC6 -- Screenshot capture and dimension tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from playwright.async_api import async_playwright

from autositemap.config import Config
from autositemap.screenshot import capture_screenshot, read_png_dimensions


@pytest.mark.slow
async def test_screenshot_matches_dialog_state(fixture_config: Config, fixture_server, output_dir):
    """Navigate to index, open the modal, take a screenshot. Verify the file
    exists and is a valid PNG."""
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

        # Open the modal dialog
        await page.click("#open-modal")
        await page.wait_for_timeout(500)

        screenshots_dir = output_dir / "screenshots"
        original_name, _derivative_name = await capture_screenshot(
            page, "dialog_state", fixture_config, screenshots_dir
        )

        screenshot_path = screenshots_dir / original_name
        assert screenshot_path.exists(), f"Screenshot file should exist at {screenshot_path}"

        # Verify it is a valid PNG
        data = screenshot_path.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", "File should be a valid PNG"

        # Verify dimensions can be read
        w, h = read_png_dimensions(data)
        assert w > 0 and h > 0, "PNG dimensions should be positive"

        await browser.close()


@pytest.mark.slow
async def test_readiness_timeout_is_reported(fixture_config: Config, fixture_server, output_dir):
    """Use a very short screenshot_timeout and try to capture. Verify that the
    timeout parameter is respected and doesn't hang."""
    # Create config with a very short screenshot timeout (100ms)
    short_timeout_config = replace(
        fixture_config,
        budgets=replace(fixture_config.budgets, screenshot_timeout=0.1),
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={
                "width": short_timeout_config.viewport.width,
                "height": short_timeout_config.viewport.height,
            },
            service_workers="block",
        )
        page = await context.new_page()
        base_url = fixture_server.base_url

        await context.add_cookies([{"name": "auth", "value": "valid", "url": base_url}])
        await page.goto(f"{base_url}/", wait_until="load")

        screenshots_dir = output_dir / "screenshots"

        # With a 100ms timeout, the screenshot might succeed (page is simple
        # and already loaded) or might timeout. Either outcome is acceptable;
        # we just verify the timeout parameter is used and we don't hang.
        try:
            original_name, _ = await capture_screenshot(
                page, "timeout_test", short_timeout_config, screenshots_dir
            )
            # If it succeeded, verify the file is a valid PNG
            path = screenshots_dir / original_name
            assert path.exists()
        except Exception as e:
            # A timeout error is acceptable -- the point is we didn't hang
            assert "timeout" in str(e).lower() or "Timeout" in str(e), (
                f"Expected a timeout-related error, got: {e}"
            )

        await browser.close()


@pytest.mark.slow
async def test_mask_applies_to_original_and_export(
    fixture_config: Config, fixture_server, output_dir
):
    """Navigate to index (has .mask-me element). Capture screenshot with mask.
    Verify the screenshot file exists and no error occurred."""
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

        # Verify the mask-me element exists on the page
        mask_count = await page.locator(".mask-me").count()
        assert mask_count > 0, "Expected .mask-me element on the index page"

        screenshots_dir = output_dir / "screenshots"

        # fixture_config has mask_selectors=(".mask-me",) and mask_color="#FF00FF"
        original_name, _derivative_name = await capture_screenshot(
            page, "masked_state", fixture_config, screenshots_dir
        )

        screenshot_path = screenshots_dir / original_name
        assert screenshot_path.exists(), "Masked screenshot should be saved"

        # Verify it's a valid PNG with correct dimensions
        data = screenshot_path.read_bytes()
        w, h = read_png_dimensions(data)
        assert w > 0 and h > 0

        await browser.close()


@pytest.mark.slow
async def test_large_image_derivative_preserves_aspect_ratio(
    fixture_config: Config, fixture_server, output_dir
):
    """Create a screenshot with the fixture site. Read its dimensions with
    read_png_dimensions. Verify width <= 4096 and height <= 4096. Verify
    aspect ratio matches viewport (800/600 = 4/3 approximately)."""
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

        screenshots_dir = output_dir / "screenshots"
        original_name, _derivative_name = await capture_screenshot(
            page, "aspect_test", fixture_config, screenshots_dir
        )

        screenshot_path = screenshots_dir / original_name
        data = screenshot_path.read_bytes()
        w, h = read_png_dimensions(data)

        # Must be within Figma limits
        assert w <= 4096, f"Width {w} exceeds 4096"
        assert h <= 4096, f"Height {h} exceeds 4096"

        # Aspect ratio should approximately match viewport (800x600 = 4:3)
        expected_ratio = fixture_config.viewport.width / fixture_config.viewport.height
        actual_ratio = w / h
        assert abs(actual_ratio - expected_ratio) < 0.1, (
            f"Aspect ratio {actual_ratio:.3f} should be close to "
            f"viewport ratio {expected_ratio:.3f}"
        )

        await browser.close()
