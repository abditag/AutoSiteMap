from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="autositemap",
        description=(
            "Crawl an authenticated website and generate a visual navigation map for Figma"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_parser = subparsers.add_parser("crawl", help="Crawl a website")
    crawl_parser.add_argument("--config", required=True, help="Path to TOML config file")
    crawl_parser.add_argument(
        "--output", help="Output directory (default: output/<name>_<timestamp>)"
    )

    export_parser = subparsers.add_parser("export", help="Export a crawl to Figma bundle")
    export_parser.add_argument("--crawl-dir", required=True, help="Path to crawl output directory")
    export_parser.add_argument(
        "--output", help="Bundle output path (default: <crawl-dir>/bundle.zip)"
    )
    export_parser.add_argument("--config", help="Config override (uses crawl's config by default)")

    report_parser = subparsers.add_parser("report", help="Generate exploration report")
    report_parser.add_argument("--crawl-dir", required=True, help="Path to crawl output directory")

    args = parser.parse_args()

    if args.command == "crawl":
        asyncio.run(_cmd_crawl(args))
    elif args.command == "export":
        _cmd_export(args)
    elif args.command == "report":
        _cmd_report(args)


async def _cmd_crawl(args: argparse.Namespace) -> None:
    from autositemap.auth import AuthError, perform_manual_login
    from autositemap.config import ConfigError, load_config
    from autositemap.crawler import explore
    from autositemap.graph import Graph
    from autositemap.report import generate_report

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Site: {config.site.name}")
    print(f"Start URL: {config.site.start_url}")
    print(f"Scope: {config.scope.url_prefix}")

    if args.output:
        output_dir = Path(args.output)
    else:
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        safe_name = config.site.name.replace(" ", "_").lower()[:30]
        output_dir = Path("output") / f"{safe_name}_{ts}"

    output_dir.mkdir(parents=True, exist_ok=True)

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={
                "width": config.viewport.width,
                "height": config.viewport.height,
            },
            service_workers="block",
        )

        try:
            page = await perform_manual_login(context, config, output_dir)
        except AuthError as e:
            print(f"\n{e}", file=sys.stderr)
            await browser.close()
            sys.exit(1)

        graph = Graph()
        try:
            graph = await explore(page, config, output_dir, graph=graph)
        except (KeyboardInterrupt, asyncio.CancelledError):
            graph.termination_reason = graph.termination_reason or "interrupted"
            print("\n  Interrupted. Saving partial results.", file=sys.stderr)
        except Exception as e:
            print(f"\nExploration error: {e}", file=sys.stderr)
            graph.termination_reason = graph.termination_reason or f"error: {e}"
        finally:
            graph_path = output_dir / "graph.json"
            graph.save(graph_path)
            print(f"\nGraph saved: {graph_path}")

            report = generate_report(graph, output_dir / "report.txt")
            print(report)

            await browser.close()

    print(f"\nOutput directory: {output_dir}")
    print("Run 'autositemap export --crawl-dir <dir>' to generate the Figma bundle.")


def _cmd_export(args: argparse.Namespace) -> None:
    from autositemap.bundle import BundleError, create_bundle, validate_bundle_images
    from autositemap.config import ConfigError, load_config
    from autositemap.graph import Graph

    crawl_dir = Path(args.crawl_dir)
    graph_path = crawl_dir / "graph.json"

    if not graph_path.exists():
        print(f"graph.json not found in {crawl_dir}", file=sys.stderr)
        sys.exit(1)

    graph = Graph.load(graph_path)

    config_path = args.config or graph.config_path
    if not config_path:
        print("No config path found. Use --config.", file=sys.stderr)
        sys.exit(1)

    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    bundle_path = Path(args.output) if args.output else crawl_dir / "bundle.zip"

    try:
        create_bundle(graph, config, crawl_dir, bundle_path)
    except BundleError as e:
        print(f"Bundle error: {e}", file=sys.stderr)
        sys.exit(1)

    warnings = validate_bundle_images(bundle_path)
    for w in warnings:
        print(f"  Warning: {w}")

    print(f"\nBundle created: {bundle_path}")
    print("Open the AutoSiteMap Figma plugin and select this file to import.")


def _cmd_report(args: argparse.Namespace) -> None:
    from autositemap.graph import Graph
    from autositemap.report import generate_report

    crawl_dir = Path(args.crawl_dir)
    graph_path = crawl_dir / "graph.json"

    if not graph_path.exists():
        print(f"graph.json not found in {crawl_dir}", file=sys.stderr)
        sys.exit(1)

    graph = Graph.load(graph_path)
    report = generate_report(graph)
    print(report)
