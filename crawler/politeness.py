"""robots.txt rules and per-host pacing."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from crawler.fetch import USER_AGENT, Response


def _host_root(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class RobotsCache:
    """One robots.txt fetch per host. 401/403 means disallow all; other errors allow all."""

    def __init__(self, get: Callable[[str], Awaitable[Response]], user_agent: str = USER_AGENT):
        self._get = get
        self._agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _parser(self, url: str) -> RobotFileParser:
        root = _host_root(url)
        lock = self._locks.setdefault(root, asyncio.Lock())
        async with lock:
            if root in self._parsers:
                return self._parsers[root]
            parser = RobotFileParser()
            try:
                response = await self._get(f"{root}/robots.txt")
            except Exception:  # noqa: BLE001 - unreachable robots.txt means no rules
                response = Response(url=root, status=404)
            if response.status in (401, 403):
                parser.disallow_all = True
            elif response.status >= 400:
                parser.allow_all = True
            else:
                parser.parse(response.text.splitlines())
            self._parsers[root] = parser
            return parser

    async def allowed(self, url: str) -> bool:
        return (await self._parser(url)).can_fetch(self._agent, url)

    async def crawl_delay(self, url: str) -> float | None:
        delay = (await self._parser(url)).crawl_delay(self._agent)
        return float(delay) if delay is not None else None


class HostPacer:
    """Serializes requests per host and spaces them at least `delay` seconds apart."""

    def __init__(
        self,
        min_delay: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.min_delay = min_delay
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, url: str, delay: float | None = None) -> None:
        host = urlsplit(url).netloc
        gap = max(self.min_delay, delay or 0.0)
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            last = self._last.get(host)
            if last is not None:
                remaining = gap - (self._clock() - last)
                if remaining > 0:
                    await self._sleep(remaining)
            self._last[host] = self._clock()
