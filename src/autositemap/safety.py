from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from playwright.async_api import BrowserContext, Page, Route

from autositemap.config import Config
from autositemap.graph import ControlRecord, Graph

_FILE_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".zip",
        ".rar",
        ".tar",
        ".gz",
        ".7z",
        ".csv",
        ".txt",
        ".rtf",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".svg",
        ".webp",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
        ".wmv",
        ".exe",
        ".dmg",
        ".msi",
        ".deb",
        ".rpm",
    }
)


def is_url_in_scope(url: str, config: Config) -> bool:
    prefix = config.scope.url_prefix
    if not url.startswith(prefix):
        return False
    if not prefix.endswith("/") and len(url) > len(prefix):
        next_char = url[len(prefix)]
        if next_char not in ("/?#"):
            return False
    return all(not re.search(pattern, url) for pattern in config.scope.deny_url_patterns)


def _resolve_href(href: str | None, page_url: str) -> str | None:
    if not href:
        return None
    if href.startswith(("javascript:", "mailto:", "tel:", "#")):
        return None
    return urljoin(page_url, href)


async def install_scope_guards(
    context: BrowserContext,
    config: Config,
    graph: Graph,
) -> None:
    async def route_handler(route: Route) -> None:
        request = route.request
        url = request.url

        if request.resource_type in ("document", "frame") and not is_url_in_scope(url, config):
            graph.add_out_of_scope(
                source_state_id=graph.root_state_id or "unknown",
                url=url,
                control_text="navigation",
            )
            await route.abort("blockedbyclient")
            return

        await route.continue_()

    await context.route("**/*", route_handler)

    _popup_tasks: list = []

    def on_popup(popup_page: Page) -> None:
        import asyncio
        import contextlib

        async def handle_popup() -> None:
            try:
                await popup_page.wait_for_load_state("commit", timeout=3000)
                popup_url = popup_page.url
                if popup_url and popup_url != "about:blank":
                    graph.add_out_of_scope(
                        source_state_id=graph.root_state_id or "unknown",
                        url=popup_url,
                        control_text="popup",
                    )
            finally:
                with contextlib.suppress(Exception):
                    await popup_page.close()

        task = asyncio.ensure_future(handle_popup())
        _popup_tasks.append(task)

    context.on("page", on_popup)


async def install_dialog_handler(page: Page) -> None:
    page.on("dialog", lambda dialog: dialog.dismiss())


_SELECTOR_GEN_JS = """
(el) => {
    if (el.dataset && el.dataset.testid) {
        return `[data-testid="${el.dataset.testid}"]`;
    }
    if (el.id) {
        return '#' + el.id;
    }

    const parts = [];
    let current = el;
    while (current && current !== document.body && current !== document.documentElement) {
        let tag = current.tagName.toLowerCase();
        const parent = current.parentElement;
        if (parent) {
            const siblings = Array.from(parent.children).filter(
                c => c.tagName === current.tagName
            );
            if (siblings.length > 1) {
                const idx = siblings.indexOf(current) + 1;
                tag += `:nth-of-type(${idx})`;
            }
        }
        parts.unshift(tag);

        if (current.id) {
            parts[0] = '#' + current.id;
            break;
        }
        current = parent;
    }

    return parts.join(' > ');
}
"""


async def discover_controls(page: Page, config: Config, page_url: str) -> list[ControlRecord]:
    all_selectors = list(config.controls.include_selectors) + list(
        config.controls.custom_selectors
    )
    combined = ", ".join(all_selectors)

    seen_selectors: set[str] = set()
    controls: list[ControlRecord] = []

    scroll_height = await page.evaluate("document.body.scrollHeight")
    viewport_height = config.viewport.height
    scroll_steps = min(
        config.budgets.max_scroll_steps,
        max(1, scroll_height // viewport_height),
    )

    for step in range(scroll_steps):
        scroll_y = step * viewport_height
        await page.evaluate(f"window.scrollTo(0, {scroll_y})")
        await page.wait_for_timeout(200)

        elements = await page.query_selector_all(combined)
        for el in elements:
            try:
                if not await el.is_visible():
                    continue
                box = await el.bounding_box()
                if not box or box["width"] <= 0 or box["height"] <= 0:
                    continue

                selector = await page.evaluate(_SELECTOR_GEN_JS, el)
                if not selector or selector in seen_selectors:
                    continue
                seen_selectors.add(selector)

                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                text = (await el.inner_text()).strip()[:100] if await el.inner_text() else ""
                href_raw = await el.get_attribute("href")
                role = await el.get_attribute("role")
                aria_label = await el.get_attribute("aria-label")
                disabled = await el.get_attribute("disabled")
                aria_disabled = await el.get_attribute("aria-disabled")
                download_attr = await el.get_attribute("download")
                input_type = await el.get_attribute("type")

                href = _resolve_href(href_raw, page_url)

                control_type = _classify_control_type(tag, role, input_type, download_attr)
                is_safe, unsafe_reason = _classify_safety(
                    el,
                    page,
                    config,
                    tag,
                    text,
                    href,
                    input_type,
                    download_attr,
                    disabled,
                    aria_disabled,
                    aria_label,
                )

                outcome = None
                destination_url = None

                if disabled is not None or aria_disabled == "true":
                    outcome = "disabled"
                    is_safe = False
                    unsafe_reason = "disabled"
                elif download_attr is not None or _is_download_href(href):
                    outcome = "download_skipped"
                    is_safe = False
                    unsafe_reason = "download"
                    destination_url = href
                elif not is_safe:
                    outcome = "unsafe_skipped"
                elif href and not is_url_in_scope(href, config):
                    outcome = "out_of_scope"
                    destination_url = href
                    is_safe = False
                    unsafe_reason = "out_of_scope"

                controls.append(
                    ControlRecord(
                        selector=selector,
                        tag=tag,
                        text=text or aria_label or "",
                        href=href,
                        role=role,
                        control_type=control_type,
                        is_safe=is_safe,
                        unsafe_reason=unsafe_reason,
                        outcome=outcome,
                        destination_url=destination_url,
                    )
                )
            except Exception:
                continue

    await page.evaluate("window.scrollTo(0, 0)")
    return controls


def _classify_control_type(
    tag: str, role: str | None, input_type: str | None, download: str | None
) -> str:
    if download is not None:
        return "download"
    if role == "tab":
        return "tab"
    if role == "menuitem":
        return "menu_item"
    if tag == "a":
        return "link"
    if tag == "button" or role == "button":
        return "button"
    if tag == "summary":
        return "toggle"
    if tag == "input" and input_type == "submit":
        return "submit"
    return "unknown"


def _classify_safety(
    el,
    page: Page,
    config: Config,
    tag: str,
    text: str,
    href: str | None,
    input_type: str | None,
    download: str | None,
    disabled: str | None,
    aria_disabled: str | None,
    aria_label: str | None,
) -> tuple[bool, str | None]:
    if disabled is not None or aria_disabled == "true":
        return False, "disabled"

    if download is not None or _is_download_href(href):
        return False, "download"

    for pattern in config.controls.unsafe_text_patterns:
        for label in (text, aria_label):
            if label and re.search(pattern, label):
                return False, f"text_pattern:{pattern}"

    if href and not is_url_in_scope(href, config):
        return False, "out_of_scope"

    if tag == "input" and input_type == "submit":
        return False, "form_submission"

    return True, None


def _is_download_href(href: str | None) -> bool:
    if not href:
        return False
    path = urlparse(href).path.lower()
    return any(path.endswith(ext) for ext in _FILE_EXTENSIONS)


async def check_unsafe_selectors(page: Page, selector: str, config: Config) -> str | None:
    for unsafe_sel in config.controls.unsafe_selectors:
        try:
            el = page.locator(selector)
            matches = await el.evaluate(
                "(el, sel) => el.matches(sel) || !!el.closest(sel)", unsafe_sel
            )
            if matches:
                return f"unsafe_selector:{unsafe_sel}"
        except Exception:
            return f"safety_eval_failed:{unsafe_sel}"
    return None


async def check_form_context(page: Page, selector: str) -> str | None:
    try:
        triggers_submit = await page.locator(selector).evaluate("""
            (el) => {
                const form = el.form || el.closest('form');
                if (!form) return false;
                const tag = el.tagName.toLowerCase();
                if (tag === 'input') return el.type === 'submit' || el.type === 'image';
                if (tag === 'button') return el.type !== 'button';
                return false;
            }
        """)
        if triggers_submit:
            return "form_submission"
    except Exception:
        return "safety_eval_failed:form_check"
    return None


async def detect_iframes(page: Page) -> bool:
    try:
        count = await page.evaluate("document.querySelectorAll('iframe').length")
        return count > 0
    except Exception:
        return False


async def post_click_scope_check(page: Page, config: Config) -> str | None:
    current_url = page.url
    if not is_url_in_scope(current_url, config):
        return current_url
    return None


async def check_session_expired(page: Page, config: Config) -> bool:
    if not config.auth.session_expired_selector:
        return False
    try:
        loc = page.locator(config.auth.session_expired_selector)
        return await loc.is_visible()
    except Exception:
        return False
