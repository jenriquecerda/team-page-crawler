"""Crawl orchestration: one polite worker per domain, many domains concurrently."""

import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from crawler.extract import Person, merge_people, parse_page
from crawler.fetch import FetchError, Fetcher
from crawler.frontier import Frontier
from crawler.politeness import HostPacer, RobotsCache
from crawler.store import Diff, Store
from crawler.urls import normalize_url, registrable_host, team_score

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrawlConfig:
    max_pages: int = 25
    max_depth: int = 2
    max_sitemap_urls: int = 20
    domain_concurrency: int = 4


@dataclass
class DomainReport:
    domain: str
    pages_fetched: int = 0
    pages_skipped_robots: int = 0
    pages_unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    diff: Diff = field(default_factory=Diff)
    complete: bool = True


def sitemap_urls(xml_text: str) -> list[str]:
    """<loc> values from a sitemap or sitemap index; tolerant of namespaces and bad XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    return [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]


class Crawler:
    def __init__(
        self,
        fetcher: Fetcher,
        store: Store,
        config: CrawlConfig | None = None,
        pacer: HostPacer | None = None,
    ):
        self.fetcher = fetcher
        self.store = store
        self.config = config or CrawlConfig()
        self.pacer = pacer or HostPacer()
        self.robots = RobotsCache(self._polite_get)

    async def _polite_get(self, url: str):
        await self.pacer.wait(url)
        return await self.fetcher.get(url)

    async def _seed(self, root: str, frontier: Frontier) -> None:
        frontier.add(root, 0)
        if not await self.robots.allowed(f"{root}/sitemap.xml"):
            return
        try:
            response = await self._polite_get(f"{root}/sitemap.xml")
        except FetchError:
            return
        if response.status != 200:
            return
        urls = [u for u in sitemap_urls(response.text) if team_score(u) > 0]
        for url in sorted(urls, key=team_score, reverse=True)[: self.config.max_sitemap_urls]:
            frontier.add(url, 1)

    async def crawl_domain(self, domain: str) -> DomainReport:
        root = normalize_url(domain if "://" in domain else f"https://{domain}")
        if root is None:
            return DomainReport(domain, errors=[f"invalid domain: {domain}"], complete=False)
        root = root.rstrip("/")
        site = registrable_host(root)
        report = DomainReport(site)
        frontier = Frontier(root, self.config.max_pages, self.config.max_depth)
        await self._seed(root, frontier)
        found: list[tuple[Person, str]] = []

        while (item := frontier.pop()) is not None:
            url, depth = item
            if not await self.robots.allowed(url):
                report.pages_skipped_robots += 1
                continue
            await self.pacer.wait(url, await self.robots.crawl_delay(url))
            try:
                response = await self.fetcher.get(url)
            except FetchError as exc:
                report.errors.append(str(exc))
                report.complete = False
                continue
            report.pages_fetched += 1
            if response.status >= 500 or response.status == 429:
                report.errors.append(f"{url}: HTTP {response.status}")
                report.complete = False
                continue
            if response.status >= 400 or not response.is_html:
                continue

            page = parse_page(response.text)
            if self.store.page_unchanged(url, response.text):
                report.pages_unchanged += 1
            self.store.save_page(url, site, response.status, response.text)
            found.extend((person, url) for person in page.people)
            for link in page.links:
                frontier.add(link, depth + 1, base=response.url)

        if len(frontier):
            report.complete = False  # budget ran out before the frontier did
        merged = merge_people([p for p, _ in found])
        source = {}
        for person, url in found:
            source.setdefault(person.name, url)
        report.people = merged
        report.diff = self.store.sync_people(
            site, [(p, source[p.name]) for p in merged], complete=report.complete
        )
        return report

    async def crawl(self, domains: list[str]) -> list[DomainReport]:
        semaphore = asyncio.Semaphore(self.config.domain_concurrency)

        async def one(domain: str) -> DomainReport:
            async with semaphore:
                try:
                    return await self.crawl_domain(domain)
                except Exception as exc:  # noqa: BLE001 - one bad site must not stop the rest
                    log.exception("crawl failed for %s", domain)
                    return DomainReport(domain, errors=[repr(exc)], complete=False)

        return await asyncio.gather(*(one(d) for d in domains))
