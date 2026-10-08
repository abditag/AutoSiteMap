# AutoSiteMap

Crawl an authenticated website via Playwright, capture screenshots, build a navigation graph, and generate a ZIP bundle that a Figma plugin imports as a visual site map with screenshots, labels, and arrows.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Install

```bash
uv sync --locked
uv run --locked playwright install chromium
```

## Usage

Three subcommands: `crawl`, `export`, `report`.

### Crawl

Opens a visible browser. Log in manually — the crawler starts automatically when it detects the readiness selector.

```bash
uv run autositemap crawl --config configs/immobilienscout24.toml
```

Optional `--output DIR` overrides the default `output/<site>_<timestamp>/` directory.

**Output:** `graph.json` (navigation graph), `screenshots/` directory, `report.txt`.

### Export

Generates the Figma-importable ZIP bundle from a previous crawl. No browser needed.

```bash
uv run autositemap export --crawl-dir output/my_crawl/
```

Optional `--output PATH` and `--config PATH` to override the bundle path or config.

### Report

Prints a human-readable coverage report from a saved graph.

```bash
uv run autositemap report --crawl-dir output/my_crawl/
```

### Figma Plugin

1. In Figma Desktop, go to Plugins > Development > Import plugin from manifest
2. Select `figma_plugin/manifest.json`
3. Run the plugin, pick the `.zip` bundle
4. The plugin creates a frame with screenshot cards, URL labels, and directional arrows

## How It Works

### Exploration

The crawler performs BFS exploration starting from `start_url`:

1. **Login** — Navigates to `login_url`, waits for you to authenticate, detects readiness via a CSS selector
2. **Fingerprinting** — Each page state is identified by `SHA-256(structural DOM) + normalized URL`. Structural DOM ignores configured selectors (timestamps, badges) and scrubs date/time patterns. `aria-expanded`, `aria-selected`, `aria-hidden`, `open`, and `hidden` attributes are included, so a dialog open vs. closed produces distinct states
3. **Control discovery** — Scrolls the page, queries `include_selectors`, generates a unique CSS selector per element, classifies each as safe or unsafe
4. **Safety classification** — A control is blocked if it matches any: `unsafe_selectors` (CSS), `unsafe_text_patterns` (regex on both visible text and `aria-label`), form submission context (`button` inside `<form>` that would trigger submit), `disabled` attribute, download link, or out-of-scope `href`. Deny rules always override allow rules
5. **Action execution** — Clicks safe controls one at a time, waits for navigation/settle, computes the new fingerprint. Same fingerprint = `no_change`, known fingerprint = cross-link, new fingerprint = new state (screenshot + discover controls + enqueue)
6. **State restoration** — Navigates to `start_url` and replays the sequence of previously verified safe clicks to return to a target state. Fingerprint is verified at each step
7. **Budgets** — Stops at `max_states`, `max_depth`, `max_actions_per_state`, or `global_timeout`. `Ctrl+C` saves partial results

### Scope Guards

- Route interception blocks out-of-scope document/frame navigations (`route.abort`)
- Post-click URL check catches redirects the route handler misses
- Popups are recorded and closed
- JS dialogs are auto-dismissed
- URL prefix matching enforces path boundaries (prevents `example.com.evil.test` matching `example.com`)

### Export Pipeline

1. **Layout** — Simplified Sugiyama algorithm. Layers by BFS depth, centered horizontally, deterministic ordering by state ID. Tree edges use top/bottom ports, cross-links use side ports
2. **Bundle** — ZIP containing `manifest.json` (states with coordinates, connections with ports, summary) + `screenshots/`. Auth-related query/fragment parameters are automatically stripped. Additional URL redaction via regex patterns
3. **Validation** — Bundle is validated: manifest structure, screenshot references, connection references, coordinate validity, image dimensions (Figma's 4096px limit)

### Figma Plugin

Pure client-side, no build pipeline. Three files: `manifest.json`, `ui.html` (ZIP extraction via native `DecompressionStream`), `code.js` (node creation). Creates `FrameNode` cards with `IMAGE` fills, text labels with hyperlinks (Inter font), and `VectorNode` arrows with per-vertex `strokeCap` for directionality. Tree edges are solid dark; cross-links are dashed.

## Configuration

TOML file with these sections. Only `site.name`, `site.start_url`, `auth.login_url`, `auth.readiness_selector`, and `scope.url_prefix` are required — everything else has defaults.

| Section | Key | Default | Purpose |
|---|---|---|---|
| `site` | `name` | — | Display name |
| `site` | `start_url` | — | BFS root (must begin with `url_prefix`) |
| `auth` | `login_url` | — | Browser opens here for manual login |
| `auth` | `readiness_selector` | — | CSS selector that signals login is complete |
| `auth` | `login_timeout` | `300` | Seconds to wait for login |
| `auth` | `session_expired_selector` | — | If visible mid-crawl, stops exploration |
| `scope` | `url_prefix` | — | URLs must start with this to be in scope |
| `scope` | `deny_url_patterns` | `[]` | Regex patterns — matching URLs are always blocked |
| `viewport` | `width`, `height` | `1280`, `720` | Browser viewport (max 4096) |
| `budgets` | `max_states` | `50` | Stop after this many states |
| `budgets` | `max_depth` | `6` | Maximum BFS depth |
| `budgets` | `max_actions_per_state` | `30` | Controls explored per state |
| `budgets` | `global_timeout` | `600` | Total crawl time in seconds |
| `budgets` | `action_timeout` | `10` | Per-click timeout |
| `budgets` | `screenshot_timeout` | `5` | Per-screenshot timeout |
| `budgets` | `max_scroll_steps` | `5` | Scroll steps for control discovery |
| `controls` | `include_selectors` | links, buttons, tabs, etc. | CSS selectors for discoverable controls |
| `controls` | `unsafe_selectors` | `[]` | CSS selectors — matched controls are never clicked |
| `controls` | `unsafe_text_patterns` | `[]` | Regex — checked against both visible text and `aria-label` |
| `controls` | `dismiss_selectors` | `[]` | Clicked to close overlays before actions |
| `controls` | `custom_selectors` | `[]` | Additional selectors appended to `include_selectors` |
| `screenshot` | `full_page` | `false` | Capture full scrollable page |
| `screenshot` | `mask_selectors` | `[]` | PII masking — elements are covered with `mask_color` |
| `screenshot` | `mask_color` | `#FF00FF` | Mask fill color |
| `fingerprint` | `ignore_selectors` | `[]` | Elements excluded from DOM hashing |
| `fingerprint` | `ignore_url_params` | `[]` | Query params stripped before URL comparison |
| `diagram` | `card_width` | `400` | Card width in the Figma layout |
| `diagram` | `card_padding` | `20` | Padding around the diagram |
| `diagram` | `horizontal_gap` | `60` | Space between columns |
| `diagram` | `vertical_gap` | `80` | Space between rows |
| `export` | `redact_url_patterns` | `[]` | Regex patterns — matches replaced with `[REDACTED]` in bundle URLs |

See `configs/immobilienscout24.toml` for a real-world example and `configs/fixture.toml` for a minimal test config.

## Safety Model

The crawler is read-only by design:

- **Never submits forms** — buttons that would trigger form submission are blocked
- **Deny overrides allow** — any deny rule match blocks the control, regardless of other classification
- **Fail closed** — if safety evaluation throws an exception, the control is treated as unsafe
- **No form filling** — the crawler clicks navigation controls only; it never types into inputs
- **Scope enforcement** — route interception + post-navigation checks + popup handling
- **Auth isolation** — `auth_state.json` and `session_storage.json` are per-output-directory, excluded from `.gitignore` and never included in export bundles
- **Auth stripping** — common auth-related query/fragment parameters (`access_token`, `token`, `jwt`, `session_id`, etc.) are automatically removed from bundle URLs

## Control Outcomes

Every discovered control gets one of these outcomes in the graph and report:

| Outcome | Meaning |
|---|---|
| `explored` | Clicked, led to a new or existing state |
| `no_change` | Clicked, page fingerprint unchanged |
| `out_of_scope` | href resolves outside `url_prefix` or matches `deny_url_patterns` |
| `unsafe_skipped` | Matched an unsafe selector, text pattern, or form context |
| `disabled` | Element has `disabled` or `aria-disabled="true"` |
| `download_skipped` | Has `download` attribute or href points to a file |
| `budget_exceeded` | Skipped due to `max_states`, `max_depth`, or `max_actions_per_state` |
| `error` | Click or navigation failed |
| `restore_failed` | Could not navigate back to the source state |
| `not_explored` | Safe but never dequeued (frontier exhausted or budget hit) |
| `session_expired` | Session expiry detected after click |

## Project Structure

```
src/autositemap/
    cli.py          — argparse, subcommand dispatch
    config.py       — TOML loading, frozen dataclasses, validation
    auth.py         — manual login flow, session persistence
    crawler.py      — BFS exploration loop, state restoration
    safety.py       — scope guards, control discovery and classification
    state.py        — DOM fingerprinting, URL normalization
    graph.py        — graph model, JSON serialization
    screenshot.py   — capture with masks, Figma dimension validation
    layout.py       — simplified Sugiyama layout algorithm
    bundle.py       — ZIP bundle creation and validation
    report.py       — human-readable coverage report

figma_plugin/
    manifest.json   — Figma plugin manifest
    code.js         — sandbox: creates frames, images, text, arrows
    ui.html         — file picker, ZIP extraction, progress display

configs/
    immobilienscout24.toml  — ImmobilienScout24 Property Hub
    fixture.toml            — local test fixture (template)
```

## Testing

```bash
uv run --locked pytest                     # all 50 tests
uv run --locked pytest -m "not slow"       # unit tests only (~1s)
uv run --locked pytest -m slow             # browser tests only (~3min)
```

The test suite uses a local fixture site (`tests/fixture_site/`) with a mutation trap — a POST endpoint that records requests. Browser tests assert zero mutations at teardown, proving the crawler never triggers unsafe actions.

## Lint

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
```
