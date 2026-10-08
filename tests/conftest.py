from __future__ import annotations

from pathlib import Path

import pytest

from autositemap.config import (
    AuthConfig,
    BudgetConfig,
    Config,
    ControlsConfig,
    DiagramConfig,
    ExportConfig,
    FingerprintConfig,
    ScopeConfig,
    ScreenshotConfig,
    SiteConfig,
    ViewportConfig,
)
from tests.fixture_site.server import FixtureServer


@pytest.fixture(scope="session")
def fixture_server():
    server = FixtureServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture()
def fixture_config(fixture_server: FixtureServer) -> Config:
    base = fixture_server.base_url
    return Config(
        site=SiteConfig(name="Fixture Test Site", start_url=f"{base}/"),
        auth=AuthConfig(
            login_url=f"{base}/login.html",
            readiness_selector="#dashboard",
            login_timeout=10,
            session_expired_selector="#login-form",
        ),
        scope=ScopeConfig(
            url_prefix=f"{base}/",
            deny_url_patterns=("/admin",),
        ),
        viewport=ViewportConfig(width=800, height=600),
        budgets=BudgetConfig(
            max_states=15,
            max_actions_per_state=20,
            max_depth=4,
            global_timeout=60,
            action_timeout=5,
            screenshot_timeout=3,
            max_scroll_steps=3,
        ),
        controls=ControlsConfig(
            include_selectors=(
                "a[href]",
                "button",
                "[role=button]",
                "[role=tab]",
                "[role=menuitem]",
                "details > summary",
            ),
            unsafe_selectors=(
                "form[method='post'] button[type='submit']",
                "[data-unsafe='true']",
            ),
            unsafe_text_patterns=(
                "(?i)delete",
                "(?i)save",
            ),
            dismiss_selectors=(
                "[data-dismiss='modal']",
                "button.modal-close",
            ),
        ),
        screenshot=ScreenshotConfig(
            full_page=False,
            mask_selectors=(".mask-me",),
            mask_color="#FF00FF",
        ),
        fingerprint=FingerprintConfig(
            ignore_selectors=(".timestamp", ".dynamic-content"),
        ),
        diagram=DiagramConfig(card_width=300, card_padding=15, horizontal_gap=40, vertical_gap=60),
        export=ExportConfig(),
        config_path=None,
    )


@pytest.fixture()
def output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "output"
    d.mkdir()
    (d / "screenshots").mkdir()
    return d


@pytest.fixture()
def clean_mutations(fixture_server: FixtureServer):
    fixture_server.clear_mutations()
    yield fixture_server
    assert len(fixture_server.mutation_log) == 0, (
        f"Mutation trap triggered! Unsafe actions were executed: {fixture_server.mutation_log}"
    )
