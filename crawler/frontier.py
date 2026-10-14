"""Per-domain crawl frontier: priority by team score, dedupe, depth and page budget."""

import heapq
import itertools
from dataclasses import dataclass, field

from crawler.urls import looks_like_html, normalize_url, same_site, team_score


@dataclass(order=True)
class _Entry:
    sort_key: tuple[int, int]
    url: str = field(compare=False)
    depth: int = field(compare=False)


class Frontier:
    def __init__(self, root: str, max_pages: int = 25, max_depth: int = 2):
        self.root = root
        self.max_pages = max_pages
        self.max_depth = max_depth
        self._heap: list[_Entry] = []
        self._seen: set[str] = set()
        self._counter = itertools.count()
        self.popped = 0

    def add(self, url: str, depth: int, base: str | None = None) -> bool:
        normalized = normalize_url(url, base)
        if (
            normalized is None
            or depth > self.max_depth
            or normalized in self._seen
            or not same_site(normalized, self.root)
            or not looks_like_html(normalized)
        ):
            return False
        self._seen.add(normalized)
        # Highest score first; ties broken by insertion order.
        key = (-team_score(normalized), next(self._counter))
        heapq.heappush(self._heap, _Entry(key, normalized, depth))
        return True

    def pop(self) -> tuple[str, int] | None:
        if not self._heap or self.popped >= self.max_pages:
            return None
        entry = heapq.heappop(self._heap)
        self.popped += 1
        return entry.url, entry.depth

    def __len__(self) -> int:
        return len(self._heap)
