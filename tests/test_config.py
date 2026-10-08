"""Tests for autositemap.config — load_config and validate_config."""

from __future__ import annotations

import pytest

from autositemap.config import Config, ConfigError, load_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_TOML_TEMPLATE = """\
[site]
name = "{name}"
start_url = "{start_url}"

[auth]
login_url = "{login_url}"
readiness_selector = "#ready"

[scope]
url_prefix = "{url_prefix}"
"""


def _write_toml(tmp_path, content: str, filename: str = "config.toml"):
    p = tmp_path / filename
    p.write_text(content)
    return p


def _minimal_valid_toml(
    name: str = "TestSite",
    start_url: str = "https://app.example.com/",
    login_url: str = "https://app.example.com/login",
    url_prefix: str = "https://app.example.com/",
) -> str:
    return _VALID_TOML_TEMPLATE.format(
        name=name,
        start_url=start_url,
        login_url=login_url,
        url_prefix=url_prefix,
    )


# ---------------------------------------------------------------------------
# test_invalid_config_fails_before_browser_launch
# ---------------------------------------------------------------------------


class TestInvalidConfigFailsBeforeBrowserLaunch:
    """Various malformed TOML files must raise ConfigError early."""

    def test_missing_start_url(self, tmp_path):
        toml = """\
[site]
name = "MySite"

[auth]
login_url = "https://example.com/login"
readiness_selector = "#ready"

[scope]
url_prefix = "https://example.com/"
"""
        with pytest.raises(ConfigError, match="Missing required config field"):
            load_config(_write_toml(tmp_path, toml))

    def test_missing_login_url(self, tmp_path):
        toml = """\
[site]
name = "MySite"
start_url = "https://example.com/"

[auth]
readiness_selector = "#ready"

[scope]
url_prefix = "https://example.com/"
"""
        with pytest.raises(ConfigError, match="Missing required config field"):
            load_config(_write_toml(tmp_path, toml))

    def test_missing_url_prefix(self, tmp_path):
        toml = """\
[site]
name = "MySite"
start_url = "https://example.com/"

[auth]
login_url = "https://example.com/login"
readiness_selector = "#ready"

[scope]
deny_url_patterns = []
"""
        with pytest.raises(ConfigError, match="Missing required config field"):
            load_config(_write_toml(tmp_path, toml))

    def test_start_url_outside_scope(self, tmp_path):
        toml = """\
[site]
name = "MySite"
start_url = "https://other.example.com/"

[auth]
login_url = "https://other.example.com/login"
readiness_selector = "#ready"

[scope]
url_prefix = "https://app.example.com/"
"""
        with pytest.raises(ConfigError, match="must begin with"):
            load_config(_write_toml(tmp_path, toml))

    def test_viewport_exceeds_4096(self, tmp_path):
        toml = _minimal_valid_toml() + "\n[viewport]\nwidth = 5000\nheight = 720\n"
        with pytest.raises(ConfigError, match="must not exceed 4096"):
            load_config(_write_toml(tmp_path, toml))

    def test_negative_budget(self, tmp_path):
        toml = _minimal_valid_toml() + "\n[budgets]\nmax_states = -1\n"
        with pytest.raises(ConfigError, match="must be positive"):
            load_config(_write_toml(tmp_path, toml))

    def test_invalid_regex_in_unsafe_text_patterns(self, tmp_path):
        toml = _minimal_valid_toml() + '\n[controls]\nunsafe_text_patterns = ["(unclosed"]\n'
        with pytest.raises(ConfigError, match="Invalid regex"):
            load_config(_write_toml(tmp_path, toml))

    def test_invalid_mask_color_format(self, tmp_path):
        toml = _minimal_valid_toml() + '\n[screenshot]\nmask_color = "red"\n'
        with pytest.raises(ConfigError, match="mask_color must be #RRGGBB"):
            load_config(_write_toml(tmp_path, toml))


# ---------------------------------------------------------------------------
# test_second_site_uses_same_crawler
# ---------------------------------------------------------------------------


def test_second_site_uses_same_crawler(tmp_path):
    """Two different valid configs produce Config objects with the same type and fields."""
    toml_a = _minimal_valid_toml(
        name="SiteA",
        start_url="https://a.example.com/",
        login_url="https://a.example.com/login",
        url_prefix="https://a.example.com/",
    )
    toml_b = _minimal_valid_toml(
        name="SiteB",
        start_url="https://b.example.com/",
        login_url="https://b.example.com/login",
        url_prefix="https://b.example.com/",
    )
    cfg_a = load_config(_write_toml(tmp_path, toml_a, "a.toml"))
    cfg_b = load_config(_write_toml(tmp_path, toml_b, "b.toml"))

    assert type(cfg_a) is type(cfg_b) is Config
    # Both must have exactly the same set of field names
    assert {f.name for f in cfg_a.__dataclass_fields__.values()} == {
        f.name for f in cfg_b.__dataclass_fields__.values()
    }


# ---------------------------------------------------------------------------
# test_config_changes_scope_viewport_and_limits
# ---------------------------------------------------------------------------


def test_config_changes_scope_viewport_and_limits(tmp_path):
    """Custom values for scope, viewport, and budgets override the defaults."""
    toml = """\
[site]
name = "Custom"
start_url = "https://custom.example.com/app/"

[auth]
login_url = "https://custom.example.com/login"
readiness_selector = "#ok"

[scope]
url_prefix = "https://custom.example.com/"

[viewport]
width = 1920
height = 1080

[budgets]
max_states = 100
max_depth = 10
global_timeout = 1200
"""
    cfg = load_config(_write_toml(tmp_path, toml))

    assert cfg.scope.url_prefix == "https://custom.example.com/"
    assert cfg.viewport.width == 1920
    assert cfg.viewport.height == 1080
    assert cfg.budgets.max_states == 100
    assert cfg.budgets.max_depth == 10
    assert cfg.budgets.global_timeout == 1200
    # Fields not overridden keep their defaults
    assert cfg.budgets.max_actions_per_state == 30
    assert cfg.budgets.action_timeout == 10
