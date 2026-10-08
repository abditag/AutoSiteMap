from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SiteConfig:
    name: str
    start_url: str


@dataclass(frozen=True)
class AuthConfig:
    login_url: str
    readiness_selector: str
    login_timeout: int = 300
    session_expired_selector: str | None = None


@dataclass(frozen=True)
class ScopeConfig:
    url_prefix: str
    deny_url_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ViewportConfig:
    width: int = 1280
    height: int = 720


@dataclass(frozen=True)
class BudgetConfig:
    max_states: int = 50
    max_actions_per_state: int = 30
    max_depth: int = 6
    global_timeout: int = 600
    action_timeout: int = 10
    screenshot_timeout: int = 5
    max_scroll_steps: int = 5


@dataclass(frozen=True)
class ControlsConfig:
    include_selectors: tuple[str, ...] = (
        "a[href]",
        "button",
        "[role=button]",
        "[role=tab]",
        "[role=menuitem]",
        "details > summary",
    )
    unsafe_selectors: tuple[str, ...] = ()
    unsafe_text_patterns: tuple[str, ...] = ()
    dismiss_selectors: tuple[str, ...] = ()
    custom_selectors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScreenshotConfig:
    full_page: bool = False
    mask_selectors: tuple[str, ...] = ()
    mask_color: str = "#FF00FF"


@dataclass(frozen=True)
class FingerprintConfig:
    ignore_selectors: tuple[str, ...] = ()
    ignore_url_params: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagramConfig:
    card_width: int = 400
    card_padding: int = 20
    horizontal_gap: int = 60
    vertical_gap: int = 80
    font_size: int = 14
    title_font_size: int = 18


@dataclass(frozen=True)
class ExportConfig:
    redact_url_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    site: SiteConfig
    auth: AuthConfig
    scope: ScopeConfig
    viewport: ViewportConfig = field(default_factory=ViewportConfig)
    budgets: BudgetConfig = field(default_factory=BudgetConfig)
    controls: ControlsConfig = field(default_factory=ControlsConfig)
    screenshot: ScreenshotConfig = field(default_factory=ScreenshotConfig)
    fingerprint: FingerprintConfig = field(default_factory=FingerprintConfig)
    diagram: DiagramConfig = field(default_factory=DiagramConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    config_path: str | None = None


class ConfigError(Exception):
    pass


def _to_tuple(val: list | tuple | None) -> tuple[str, ...]:
    if val is None:
        return ()
    return tuple(val)


def _compile_patterns(patterns: tuple[str, ...], label: str) -> None:
    for p in patterns:
        try:
            re.compile(p)
        except re.error as e:
            raise ConfigError(f"Invalid regex in {label}: {p!r} — {e}") from e


def load_config(path: str | Path, overrides: dict | None = None) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    if overrides:
        for key, val in overrides.items():
            section, _, field_name = key.partition(".")
            if section in raw and field_name:
                raw[section][field_name] = val
            elif not field_name:
                raw[section] = val

    try:
        site_raw = raw.get("site", {})
        site = SiteConfig(
            name=site_raw["name"],
            start_url=site_raw["start_url"],
        )

        auth_raw = raw.get("auth", {})
        auth = AuthConfig(
            login_url=auth_raw["login_url"],
            readiness_selector=auth_raw["readiness_selector"],
            login_timeout=auth_raw.get("login_timeout", 300),
            session_expired_selector=auth_raw.get("session_expired_selector"),
        )

        scope_raw = raw.get("scope", {})
        scope = ScopeConfig(
            url_prefix=scope_raw["url_prefix"],
            deny_url_patterns=_to_tuple(scope_raw.get("deny_url_patterns")),
        )
    except KeyError as e:
        raise ConfigError(f"Missing required config field: {e}") from e

    vp_raw = raw.get("viewport", {})
    viewport = ViewportConfig(
        width=vp_raw.get("width", 1280),
        height=vp_raw.get("height", 720),
    )

    b_raw = raw.get("budgets", {})
    budgets = BudgetConfig(
        max_states=b_raw.get("max_states", 50),
        max_actions_per_state=b_raw.get("max_actions_per_state", 30),
        max_depth=b_raw.get("max_depth", 6),
        global_timeout=b_raw.get("global_timeout", 600),
        action_timeout=b_raw.get("action_timeout", 10),
        screenshot_timeout=b_raw.get("screenshot_timeout", 5),
        max_scroll_steps=b_raw.get("max_scroll_steps", 5),
    )

    c_raw = raw.get("controls", {})
    controls = ControlsConfig(
        include_selectors=_to_tuple(c_raw.get("include_selectors"))
        or ControlsConfig.include_selectors,
        unsafe_selectors=_to_tuple(c_raw.get("unsafe_selectors")),
        unsafe_text_patterns=_to_tuple(c_raw.get("unsafe_text_patterns")),
        dismiss_selectors=_to_tuple(c_raw.get("dismiss_selectors")),
        custom_selectors=_to_tuple(c_raw.get("custom_selectors")),
    )

    s_raw = raw.get("screenshot", {})
    screenshot = ScreenshotConfig(
        full_page=s_raw.get("full_page", False),
        mask_selectors=_to_tuple(s_raw.get("mask_selectors")),
        mask_color=s_raw.get("mask_color", "#FF00FF"),
    )

    fp_raw = raw.get("fingerprint", {})
    fingerprint = FingerprintConfig(
        ignore_selectors=_to_tuple(fp_raw.get("ignore_selectors")),
        ignore_url_params=_to_tuple(fp_raw.get("ignore_url_params")),
    )

    d_raw = raw.get("diagram", {})
    diagram = DiagramConfig(
        card_width=d_raw.get("card_width", 400),
        card_padding=d_raw.get("card_padding", 20),
        horizontal_gap=d_raw.get("horizontal_gap", 60),
        vertical_gap=d_raw.get("vertical_gap", 80),
        font_size=d_raw.get("font_size", 14),
        title_font_size=d_raw.get("title_font_size", 18),
    )

    e_raw = raw.get("export", {})
    export = ExportConfig(
        redact_url_patterns=_to_tuple(e_raw.get("redact_url_patterns")),
    )

    config = Config(
        site=site,
        auth=auth,
        scope=scope,
        viewport=viewport,
        budgets=budgets,
        controls=controls,
        screenshot=screenshot,
        fingerprint=fingerprint,
        diagram=diagram,
        export=export,
        config_path=str(path),
    )

    validate_config(config)
    return config


def validate_config(config: Config) -> None:
    if not config.site.start_url.startswith(config.scope.url_prefix):
        raise ConfigError(
            f"start_url {config.site.start_url!r} must begin with "
            f"scope.url_prefix {config.scope.url_prefix!r}"
        )

    if config.viewport.width <= 0 or config.viewport.height <= 0:
        raise ConfigError("Viewport dimensions must be positive")
    if config.viewport.width > 4096 or config.viewport.height > 4096:
        raise ConfigError("Viewport dimensions must not exceed 4096 (Figma image limit)")

    for name in (
        "max_states",
        "max_actions_per_state",
        "max_depth",
        "global_timeout",
        "action_timeout",
        "screenshot_timeout",
        "max_scroll_steps",
    ):
        if getattr(config.budgets, name) <= 0:
            raise ConfigError(f"budgets.{name} must be positive")

    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", config.screenshot.mask_color):
        raise ConfigError(
            f"screenshot.mask_color must be #RRGGBB, got {config.screenshot.mask_color!r}"
        )

    _compile_patterns(config.controls.unsafe_text_patterns, "controls.unsafe_text_patterns")
    _compile_patterns(config.scope.deny_url_patterns, "scope.deny_url_patterns")
    _compile_patterns(config.export.redact_url_patterns, "export.redact_url_patterns")
