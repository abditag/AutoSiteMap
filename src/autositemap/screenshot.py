from __future__ import annotations

import struct
from pathlib import Path

from playwright.async_api import Page

from autositemap.config import Config


def read_png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a valid PNG file")
    width = struct.unpack(">I", data[16:20])[0]
    height = struct.unpack(">I", data[20:24])[0]
    return width, height


async def capture_screenshot(
    page: Page,
    state_id: str,
    config: Config,
    screenshots_dir: Path,
) -> tuple[str, str | None]:
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    mask_locators = []
    for sel in config.screenshot.mask_selectors:
        loc = page.locator(sel)
        try:
            if await loc.count() > 0:
                mask_locators.append(loc)
        except Exception:
            pass

    original_name = f"{state_id}.png"
    original_path = screenshots_dir / original_name

    await page.screenshot(
        path=str(original_path),
        full_page=config.screenshot.full_page,
        mask=mask_locators if mask_locators else None,
        mask_color=config.screenshot.mask_color,
        animations="disabled",
        timeout=config.budgets.screenshot_timeout * 1000,
        scale="css",
    )

    derivative_name: str | None = None

    if config.screenshot.full_page:
        data = original_path.read_bytes()
        w, h = read_png_dimensions(data)
        if w > 4096 or h > 4096:
            derivative_name = f"{state_id}_figma.png"
            derivative_path = screenshots_dir / derivative_name
            await page.screenshot(
                path=str(derivative_path),
                full_page=False,
                mask=mask_locators if mask_locators else None,
                mask_color=config.screenshot.mask_color,
                animations="disabled",
                timeout=config.budgets.screenshot_timeout * 1000,
                scale="css",
            )
        else:
            derivative_name = original_name
    else:
        derivative_name = original_name

    return original_name, derivative_name


def get_derivative_path(
    screenshots_dir: Path, original_name: str, derivative_name: str | None
) -> Path:
    name = derivative_name or original_name
    return screenshots_dir / name


def validate_figma_dimensions(path: Path) -> bool:
    data = path.read_bytes()
    try:
        w, h = read_png_dimensions(data)
        return w <= 4096 and h <= 4096
    except ValueError:
        return False
