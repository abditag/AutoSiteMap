from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.async_api import BrowserContext, Page

from autositemap.config import Config


class AuthError(Exception):
    pass


async def perform_manual_login(
    context: BrowserContext,
    config: Config,
    output_dir: Path,
) -> Page:
    page = await context.new_page()
    await page.goto(config.auth.login_url, wait_until="load")

    print(
        "\n"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║  Please log in manually in the browser window.             ║\n"
        "║  The crawler will start automatically when ready.          ║\n"
        "╚══════════════════════════════════════════════════════════════╝\n"
    )

    deadline = time.monotonic() + config.auth.login_timeout
    ready = False

    while time.monotonic() < deadline:
        try:
            current_url = page.url
            if current_url.startswith(config.scope.url_prefix):
                try:
                    await page.wait_for_selector(config.auth.readiness_selector, timeout=3000)
                    ready = True
                    break
                except Exception:
                    pass
        except Exception:
            pass

        await page.wait_for_timeout(2000)

    if not ready:
        print(
            "\n⚠  Login timeout reached. Saving partial state and exiting.\n"
            "   Re-run with the same output directory to resume.\n"
        )
        await _save_auth_state(context, page, output_dir)
        raise AuthError(
            f"Login not completed within {config.auth.login_timeout}s. "
            "Readiness selector not found."
        )

    print("✓ Login detected. Starting exploration.\n")
    await _save_auth_state(context, page, output_dir)
    return page


async def _save_auth_state(context: BrowserContext, page: Page, output_dir: Path) -> None:
    auth_path = output_dir / "auth_state.json"
    await context.storage_state(path=str(auth_path))

    try:
        session_data = await page.evaluate("() => JSON.stringify(sessionStorage)")
        session_path = output_dir / "session_storage.json"
        session_path.write_text(session_data)
    except Exception:
        pass


async def restore_session(context: BrowserContext, output_dir: Path) -> bool:
    session_path = output_dir / "session_storage.json"
    if not session_path.exists():
        return False

    try:
        session_data = json.loads(session_path.read_text())
        script = f"""
            () => {{
                const data = {json.dumps(session_data)};
                for (const [key, value] of Object.entries(data)) {{
                    sessionStorage.setItem(key, value);
                }}
            }}
        """
        await context.add_init_script(script)
        return True
    except Exception:
        return False
