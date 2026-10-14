import asyncio
from pathlib import Path

from crawler.crawl import CrawlConfig, Crawler, sitemap_urls
from crawler.fetch import Fetcher, Response, RetryConfig
from crawler.politeness import HostPacer
from crawler.store import Store

TEAM_HTML = (Path(__file__).parent / "fixtures" / "team_cards.html").read_text()
HTML = {"content-type": "text/html; charset=utf-8"}


async def no_sleep(_):
    return None


def fake_site(pages: dict[str, Response]):
    requested: list[str] = []

    async def transport(url):
        requested.append(url)
        return pages.get(url, Response(url, 404))

    return transport, requested


def build(pages, **config):
    transport, requested = fake_site(pages)
    crawler = Crawler(
        Fetcher(transport, RetryConfig(max_attempts=2), sleep=no_sleep),
        Store(),
        CrawlConfig(**config),
        pacer=HostPacer(min_delay=0, sleep=no_sleep),
    )
    return crawler, requested


HOME = Response(
    "https://acme.com/",
    200,
    HTML,
    '<a href="/blog">Blog</a> <a href="/about/team">Team</a> <a href="/private/hr">HR</a>',
)
SITE = {
    "https://acme.com/robots.txt": Response("r", 200, text="User-agent: *\nDisallow: /private\n"),
    "https://acme.com/": HOME,
    "https://acme.com/about/team": Response("https://acme.com/about/team", 200, HTML, TEAM_HTML),
    "https://acme.com/blog": Response("https://acme.com/blog", 200, HTML, "<p>Posts</p>"),
}


def test_crawls_finds_team_and_respects_robots():
    crawler, requested = build(SITE)
    report = asyncio.run(crawler.crawl_domain("acme.com"))
    names = {p.name for p in report.people}
    assert {"Ana López", "Luis de la Garza", "Priya Raman", "Sara Kim"} <= names
    assert "https://acme.com/private/hr" not in requested
    assert report.pages_skipped_robots >= 1
    assert sorted(report.diff.added) == sorted(names)


def test_team_page_is_fetched_before_blog():
    crawler, requested = build(SITE)
    asyncio.run(crawler.crawl_domain("acme.com"))
    pages = [u for u in requested if not u.endswith(("robots.txt", "sitemap.xml"))]
    assert pages.index("https://acme.com/about/team") < pages.index("https://acme.com/blog")


def test_page_budget_marks_crawl_incomplete():
    crawler, _ = build(SITE, max_pages=1)
    report = asyncio.run(crawler.crawl_domain("acme.com"))
    assert report.pages_fetched == 1
    assert not report.complete


def test_sitemap_seeds_team_pages_not_linked_from_home():
    sitemap = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://acme.com/leadership</loc></url>"
        "<url><loc>https://acme.com/blog/post-1</loc></url></urlset>"
    )
    pages = {
        "https://acme.com/": Response("https://acme.com/", 200, HTML, "<p>Hi</p>"),
        "https://acme.com/sitemap.xml": Response("s", 200, {"content-type": "text/xml"}, sitemap),
        "https://acme.com/leadership": Response(
            "https://acme.com/leadership", 200, HTML, TEAM_HTML
        ),
    }
    crawler, requested = build(pages)
    report = asyncio.run(crawler.crawl_domain("acme.com"))
    assert "https://acme.com/leadership" in requested
    assert "https://acme.com/blog/post-1" not in requested
    assert report.people


def test_server_errors_are_reported_and_keep_people_active():
    crawler, _ = build(SITE)
    asyncio.run(crawler.crawl_domain("acme.com"))
    broken = dict(SITE)
    broken["https://acme.com/about/team"] = Response("t", 503)
    crawler2, _ = build(broken)
    crawler2.store = crawler.store
    report = asyncio.run(crawler2.crawl_domain("acme.com"))
    assert not report.complete
    assert any("503" in e for e in report.errors)
    assert report.diff.removed == []


def test_one_failing_domain_does_not_stop_others():
    crawler, _ = build(SITE)
    reports = asyncio.run(crawler.crawl(["acme.com", "not a domain"]))
    assert reports[0].people
    assert reports[1].errors


def test_sitemap_parser_handles_index_and_bad_xml():
    index = "<sitemapindex><sitemap><loc> https://a.com/s1.xml </loc></sitemap></sitemapindex>"
    assert sitemap_urls(index) == ["https://a.com/s1.xml"]
    assert sitemap_urls("<not xml") == []
