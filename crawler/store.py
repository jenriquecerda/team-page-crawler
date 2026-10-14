"""SQLite storage: page hashes for skip-if-unchanged, people with first/last seen and diffs."""

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from crawler.extract import Person, name_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url          TEXT PRIMARY KEY,
    domain       TEXT NOT NULL,
    status       INTEGER NOT NULL,
    content_hash TEXT,
    fetched_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS people (
    domain      TEXT NOT NULL,
    name_key    TEXT NOT NULL,
    name        TEXT NOT NULL,
    title       TEXT NOT NULL,
    method      TEXT NOT NULL,
    confidence  REAL NOT NULL,
    source_url  TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (domain, name_key)
);
CREATE INDEX IF NOT EXISTS ix_people_domain_active ON people (domain, active);
"""


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


@dataclass
class Diff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    title_changed: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.title_changed)


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    def page_unchanged(self, url: str, text: str) -> bool:
        row = self.db.execute("SELECT content_hash FROM pages WHERE url = ?", (url,)).fetchone()
        return bool(row and row["content_hash"] == content_hash(text))

    def save_page(self, url: str, domain: str, status: int, text: str | None) -> None:
        self.db.execute(
            """
            INSERT INTO pages (url, domain, status, content_hash, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET status = excluded.status,
                content_hash = excluded.content_hash, fetched_at = excluded.fetched_at
            """,
            (url, domain, status, content_hash(text) if text else None, self._now()),
        )
        self.db.commit()

    def known_people(self, domain: str) -> dict[str, sqlite3.Row]:
        rows = self.db.execute(
            "SELECT * FROM people WHERE domain = ? AND active = 1", (domain,)
        ).fetchall()
        return {r["name_key"]: r for r in rows}

    def sync_people(
        self, domain: str, found: list[tuple[Person, str]], complete: bool = True
    ) -> Diff:
        """Upsert people seen in this crawl and return what changed.

        `found` pairs each person with the URL they were found on. When `complete` is False
        (the crawl was cut short), people not seen are kept active rather than removed.
        """
        now = self._now()
        before = self.known_people(domain)
        diff = Diff()
        seen: set[str] = set()

        for person, url in found:
            key = name_key(person.name)
            if key in seen:
                continue
            seen.add(key)
            previous = before.get(key)
            if previous is None:
                diff.added.append(person.name)
            elif previous["title"] != person.title:
                diff.title_changed.append((person.name, previous["title"], person.title))
            self.db.execute(
                """
                INSERT INTO people (domain, name_key, name, title, method, confidence,
                                    source_url, first_seen, last_seen, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(domain, name_key) DO UPDATE SET
                    name = excluded.name, title = excluded.title, method = excluded.method,
                    confidence = excluded.confidence, source_url = excluded.source_url,
                    last_seen = excluded.last_seen, active = 1
                """,
                (domain, key, person.name, person.title, person.method, person.confidence,
                 url, now, now),
            )

        if complete:
            for key, row in before.items():
                if key not in seen:
                    diff.removed.append(row["name"])
                    self.db.execute(
                        "UPDATE people SET active = 0 WHERE domain = ? AND name_key = ?",
                        (domain, key),
                    )
        self.db.commit()
        return diff

    def export_rows(self, domain: str | None = None) -> list[dict]:
        query = (
            "SELECT domain, name, title, method, confidence, source_url, first_seen, "
            "last_seen FROM people WHERE active = 1"
        )
        params: tuple = ()
        if domain:
            query += " AND domain = ?"
            params = (domain,)
        query += " ORDER BY domain, name"
        return [dict(r) for r in self.db.execute(query, params).fetchall()]
