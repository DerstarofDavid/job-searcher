"""Command-line interface designed for Windows Task Scheduler and manual runs."""

from __future__ import annotations

import argparse
import os
import platform
import sys
import webbrowser
from pathlib import Path

from .config import DEFAULT_CONFIG, company_bucket, load_config, load_dotenv
from .pipeline import run_demo, run_scan
from .search import build_queries
from .storage import JobStore
from .utils import company_matches


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="davids-job-finder",
        description="Deep, repeatable Swiss job search using David's saved profile and exclusions.",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to job_filter.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Run a live online search")
    scan.add_argument("--mode", choices=("quick", "standard", "deep"), default=None)
    scan.add_argument("--provider", choices=("auto", "bing", "duckduckgo", "tavily"), default=None)
    scan.add_argument("--query-limit", type=int, help="Developer/test limit; omit for full coverage")
    scan.add_argument("--no-notify", action="store_true", help="Do not send configured alerts")
    scan.add_argument("--open", action="store_true", help="Open the HTML report when complete")

    demo = subparsers.add_parser("demo", help="Run an offline end-to-end demonstration")
    demo.add_argument("--open", action="store_true", help="Open the demo HTML report")

    doctor = subparsers.add_parser("doctor", help="Check configuration and runtime setup")
    doctor.add_argument("--show-queries", action="store_true")

    company = subparsers.add_parser("company", help="Maintain applied/rejected/excluded company lists")
    company_sub = company.add_subparsers(dest="company_command", required=True)
    company_sub.add_parser("list", help="Show all company exclusions")
    add = company_sub.add_parser("add", help="Add a company")
    add.add_argument("name")
    add.add_argument("--status", choices=("applied", "waiting", "rejected", "blocked"), required=True)
    remove = company_sub.add_parser("remove", help="Remove a company from one status list")
    remove.add_argument("name")
    remove.add_argument("--status", choices=("applied", "waiting", "rejected", "blocked"), required=True)
    return parser


def _open(path: str) -> None:
    try:
        webbrowser.open(Path(path).resolve().as_uri())
    except Exception as exc:
        print(f"Could not open browser automatically: {exc}", file=sys.stderr)


def _doctor(config) -> int:
    print("David's Job Finder — setup check")
    print(f"Python: {platform.python_version()} ({sys.executable})")
    print(f"Config: {config.path}")
    print(f"Default mode/provider: {config.search['default_mode']} / {config.search['default_provider']}")
    print(f"Tavily: {'API key enabled' if os.environ.get('TAVILY_API_KEY') else 'keyless mode available for light tests'}")
    db_path = config.resolve_path(config.reports["database"])
    store = JobStore(db_path)
    try:
        stats = store.stats()
    finally:
        store.close()
    print(f"History: {stats['jobs']} jobs across {stats['scans']} scans; last run: {stats['latest_scan'] or 'never'}")
    print(f"Reports: {config.resolve_path(config.reports['directory'])}")
    print("Configuration and database: OK")
    return 0


def _company(config, args) -> int:
    if args.company_command == "list":
        for label, key in (
            ("Applied / waiting", "applied_waiting_companies"),
            ("Rejected", "rejected_companies"),
            ("Reviewed / blocked", "blocked_companies"),
        ):
            print(f"\n{label}:")
            for company in config.filter.get(key, []):
                print(f"  - {company}")
        return 0
    bucket = company_bucket(args.status)
    companies = config.filter.setdefault(bucket, [])
    if args.company_command == "add":
        if any(company_matches(args.name, item) for item in companies):
            print(f"Already present in {bucket}: {args.name}")
            return 0
        companies.append(args.name)
        companies.sort(key=str.casefold)
        config.save()
        print(f"Added {args.name} to {bucket}")
        return 0
    original = len(companies)
    companies[:] = [item for item in companies if not company_matches(args.name, item)]
    if len(companies) == original:
        print(f"No matching company found in {bucket}: {args.name}", file=sys.stderr)
        return 1
    config.save()
    print(f"Removed {args.name} from {bucket}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "doctor":
            code = _doctor(config)
            if args.show_queries:
                queries = build_queries(config.search, config.search["default_mode"])
                print(f"\n{len(queries)} default deep-search queries:")
                for index, query in enumerate(queries, 1):
                    print(f"{index:>2}. {query}")
            return code
        if args.command == "company":
            return _company(config, args)
        if args.command == "demo":
            result = run_demo(config)
        else:
            mode = args.mode or config.search["default_mode"]
            provider = args.provider or config.search["default_provider"]
            result = run_scan(
                config,
                mode=mode,
                provider_name=provider,
                query_limit=args.query_limit,
                send_notifications=not args.no_notify,
            )
        print("\nSearch complete")
        print(f"Accepted candidates: {len(result.jobs)}")
        print(f"Removed by hard filters: {len(result.removed)}")
        print(f"HTML report: {result.report_paths['latest_html']}")
        print(f"Markdown report: {result.report_paths['latest_markdown']}")
        if getattr(args, "open", False):
            _open(result.report_paths["latest_html"])
        return 0
    except KeyboardInterrupt:
        print("\nSearch cancelled safely; completed history is preserved.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
