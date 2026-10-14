import asyncio
import random
from datetime import UTC, datetime

from crawler.fetch import Fetcher, Response, RetryConfig, retry_after_seconds
from crawler.politeness import HostPacer, RobotsCache


class Recorder:
    def __init__(self):
        self.sleeps = []

    async def sleep(self, seconds):
        self.sleeps.append(seconds)


def scripted(*responses):
    calls = []

    async def transport(url):
        calls.append(url)
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return transport, calls


def test_retries_503_then_succeeds():
    rec = Recorder()
    transport, calls = scripted(Response("u", 503), Response("u", 200, text="ok"))
    fetcher = Fetcher(transport, RetryConfig(max_attempts=3), sleep=rec.sleep, rng=random.Random(1))
    response = asyncio.run(fetcher.get("u"))
    assert response.status == 200
    assert len(calls) == 2
    assert len(rec.sleeps) == 1


def test_retry_after_header_is_respected():
    rec = Recorder()
    transport, _ = scripted(Response("u", 429, {"retry-after": "7"}), Response("u", 200))
    asyncio.run(Fetcher(transport, sleep=rec.sleep).get("u"))
    assert rec.sleeps == [7.0]


def test_client_errors_are_not_retried():
    transport, calls = scripted(Response("u", 404))
    assert asyncio.run(Fetcher(transport, sleep=Recorder().sleep).get("u")).status == 404
    assert len(calls) == 1


def test_gives_up_and_returns_last_retryable_response():
    transport, calls = scripted(Response("u", 503))
    fetcher = Fetcher(transport, RetryConfig(max_attempts=3), sleep=Recorder().sleep)
    assert asyncio.run(fetcher.get("u")).status == 503
    assert len(calls) == 3


def test_retry_after_http_date():
    now = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)
    assert retry_after_seconds("Wed, 14 Oct 2026 12:00:30 GMT", now) == 30
    assert retry_after_seconds("garbage", now) is None


ROBOTS = "User-agent: *\nDisallow: /private\nCrawl-delay: 5\n"


def robots_get(status=200, text=ROBOTS):
    fetched = []

    async def get(url):
        fetched.append(url)
        return Response(url, status, text=text)

    return get, fetched


def test_robots_rules_and_crawl_delay_cached_per_host():
    get, fetched = robots_get()
    robots = RobotsCache(get)

    async def run():
        return (
            await robots.allowed("https://acme.com/team"),
            await robots.allowed("https://acme.com/private/x"),
            await robots.crawl_delay("https://acme.com/"),
        )

    assert asyncio.run(run()) == (True, False, 5.0)
    assert fetched == ["https://acme.com/robots.txt"]


def test_forbidden_robots_disallows_everything_and_missing_allows():
    get, _ = robots_get(status=403)
    assert not asyncio.run(RobotsCache(get).allowed("https://acme.com/team"))
    get, _ = robots_get(status=404)
    assert asyncio.run(RobotsCache(get).allowed("https://acme.com/team"))


def test_pacer_spaces_requests_to_the_same_host():
    now = [100.0]
    rec = Recorder()

    async def sleep(seconds):
        rec.sleeps.append(seconds)
        now[0] += seconds

    pacer = HostPacer(min_delay=1.0, clock=lambda: now[0], sleep=sleep)

    async def run():
        await pacer.wait("https://acme.com/a")
        await pacer.wait("https://acme.com/b", delay=5)
        await pacer.wait("https://other.com/a")

    asyncio.run(run())
    assert rec.sleeps == [5.0]
