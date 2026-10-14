"""Command line: `team-crawler crawl acme.com northwind.io` and `team-crawler export`."""

import argparse
import asyncio
import csv
import json
import logging
import sys
from pathlib import Path

from crawler.crawl import CrawlConfig, Crawler, DomainReport
from crawler.fetch import Fetcher, httpx_transport
from crawler.politeness import HostPacer
from crawler.store import Store


def _read_domains(args) -> list[str]:
    domains = list(args.domains)
    if args.file:
        domains += [
            line.strip()
            for line in Path(args.file).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
    return list(dict.fromkeys(domains))


def format_report(report: DomainReport) -> str:
    lines = [
        f"{report.domain}: {len(report.people)} people, {report.pages_fetched} pages fetched, "
        f"{report.pages_skipped_robots} blocked by robots.txt"
        + ("" if report.complete else " (incomplete)")
    ]
    for name in report.diff.added:
        lines.append(f"  + {name}")
    for name in report.diff.removed:
        lines.append(f"  - {name}")
    for name, old, new in report.diff.title_changed:
        lines.append(f"  ~ {name}: {old} -> {new}")
    for error in report.errors[:5]:
        lines.append(f"  ! {error}")
    return "\n".join(lines)


async def _crawl(args) -> int:
    domains = _read_domains(args)
    if not domains:
        print("no domains given", file=sys.stderr)
        return 2
    crawler = Crawler(
        Fetcher(httpx_transport(timeout=args.timeout)),
        Store(args.db),
        CrawlConfig(max_pages=args.max_pages, max_depth=args.max_depth),
        pacer=HostPacer(min_delay=args.delay),
    )
    reports = await crawler.crawl(domains)
    for report in reports:
        print(format_report(report))
    return 0 if all(not r.errors for r in reports) else 1


def _export(args) -> int:
    rows = Store(args.db).export_rows(args.domain)
    if args.format == "json":
        json.dump(rows, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        fields = ["domain", "name", "title", "method", "confidence", "source_url",
                  "first_seen", "last_seen"]
        writer = csv.DictWriter(sys.stdout, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="team-crawler", description=__doc__)
    parser.add_argument("--db", default="crawler.db", help="SQLite file (default: crawler.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="crawl domains and print what changed")
    crawl.add_argument("domains", nargs="*")
    crawl.add_argument("-f", "--file", help="file with one domain per line")
    crawl.add_argument("--max-pages", type=int, default=25)
    crawl.add_argument("--max-depth", type=int, default=2)
    crawl.add_argument("--delay", type=float, default=1.0, help="min seconds between requests")
    crawl.add_argument("--timeout", type=float, default=15.0)

    export = sub.add_parser("export", help="export active people")
    export.add_argument("--domain")
    export.add_argument("--format", choices=["csv", "json"], default="csv")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    if args.command == "crawl":
        return asyncio.run(_crawl(args))
    return _export(args)


if __name__ == "__main__":
    raise SystemExit(main())
