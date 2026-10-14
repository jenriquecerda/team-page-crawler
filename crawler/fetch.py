"""HTTP fetching with retries. Transport is injectable so tests never touch the network."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

USER_AGENT = "TeamPageCrawler/0.1 (+https://github.com/jenriquecerda/team-page-crawler)"
RETRYABLE = {429, 500, 502, 503, 504}


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    text: str = ""

    @property
    def is_html(self) -> bool:
        return "html" in self.headers.get("content-type", "text/html").lower()


Transport = Callable[[str], Awaitable[Response]]


class FetchError(Exception):
    pass


def retry_after_seconds(value: str | None, now: datetime | None = None) -> float | None:
    """Parse Retry-After as seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    now = now or datetime.now(UTC)
    return max((when - now).total_seconds(), 0.0)


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0


class Fetcher:
    def __init__(
        self,
        transport: Transport,
        retry: RetryConfig | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ):
        self._transport = transport
        self._retry = retry or RetryConfig()
        self._sleep = sleep
        self._rng = rng or random.Random()

    def _backoff(self, attempt: int) -> float:
        cap = min(self._retry.max_delay, self._retry.base_delay * 2**attempt)
        return self._rng.uniform(cap / 2, cap)

    async def get(self, url: str) -> Response:
        """Return the final response; retry 429/5xx and network errors with backoff."""
        last: Response | None = None
        for attempt in range(self._retry.max_attempts):
            try:
                response = await self._transport(url)
            except (OSError, TimeoutError) as exc:
                if attempt + 1 == self._retry.max_attempts:
                    raise FetchError(f"{url}: {exc}") from exc
                await self._sleep(self._backoff(attempt))
                continue
            if response.status not in RETRYABLE:
                return response
            last = response
            if attempt + 1 < self._retry.max_attempts:
                delay = retry_after_seconds(response.headers.get("retry-after"))
                await self._sleep(
                    min(delay, self._retry.max_delay) if delay is not None
                    else self._backoff(attempt)
                )
        assert last is not None
        return last


def httpx_transport(timeout: float = 15.0) -> Transport:
    """Real transport. Imported lazily so the core needs only the standard library."""
    import httpx

    client = httpx.AsyncClient(
        headers={"user-agent": USER_AGENT, "accept": "text/html,application/xhtml+xml"},
        follow_redirects=True,
        timeout=timeout,
    )

    async def send(url: str) -> Response:
        try:
            r = await client.get(url)
        except httpx.TransportError as exc:
            raise OSError(str(exc)) from exc
        return Response(
            url=str(r.url),
            status=r.status_code,
            headers={k.lower(): v for k, v in r.headers.items()},
            text=r.text if r.status_code < 400 else "",
        )

    return send
