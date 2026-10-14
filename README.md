# Team Page Crawler

A polite crawler that finds company team and leadership pages, extracts **people and their
titles**, and reports **what changed** since the last crawl: who joined, who left and who
got a new title.

```text
$ team-crawler crawl acme.com northwind.io
acme.com: 4 people, 6 pages fetched, 1 blocked by robots.txt
  + Ana López
  + Luis de la Garza
  ~ Priya Raman: Director of RevOps -> Head of Revenue Operations
  - Tom Becker
northwind.io: 2 people, 3 pages fetched, 0 blocked by robots.txt
```

Design, tradeoffs and non-goals: [docs/design.md](docs/design.md).

## How it works

```
domains ─► per-domain worker (N in parallel)
             │
             ├─ seed: "/" + team-like URLs from sitemap.xml
             ├─ priority frontier: /team, /leadership, /about first; same-site, depth + page budget
             ├─ robots.txt (cached per host) + Crawl-delay ─► per-host pacer (1 request at a time)
             ├─ fetch: retry 429/5xx with jittered backoff, honour Retry-After
             ├─ extract: JSON-LD Person (0.95) ─► HTML name+title cards (0.70) ─► merge by name
             └─ SQLite: page hashes, people with first/last seen ─► diff (added / removed / changed)
```

### Being a good citizen

- **robots.txt is law.** Disallowed paths are skipped and counted; a 401/403 on robots.txt
  means the whole site is off limits.
- **Slow by default.** One request at a time per host, at least 1 s apart, longer if the
  site sets `Crawl-delay`. `Retry-After` is honoured on 429/503.
- **Identifies itself** with a User-Agent that links back to this repo.
- **Small footprint.** A page budget (25 by default), and the crawl goes straight for likely
  team pages instead of crawling the whole site.
- **Only public, professional data.** Name, title and the page it came from. No emails,
  phones, logins or anti-bot workarounds.

### Correctness choices

- A crawl cut short (page budget, 5xx, network errors) is marked **incomplete**, and nobody
  is reported as "removed" from an incomplete crawl.
- Every person records its **extraction method and confidence**, so consumers can filter
  heuristic results.
- Pure standard library for parsing and storage (`html.parser`, `json`, `sqlite3`,
  `urllib.robotparser`); `httpx` is the only runtime dependency. The network sits behind an
  injectable transport, so the whole crawler is tested against fake sites.

## Usage

```bash
pip install .
team-crawler crawl acme.com northwind.io          # or: team-crawler crawl -f domains.txt
team-crawler crawl acme.com --max-pages 10 --delay 2
team-crawler export --format csv > people.csv     # active people, all domains
team-crawler export --domain acme.com --format json
```

## Develop

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check .
```

| Path | What |
| --- | --- |
| `crawler/urls.py`, `frontier.py` | URL normalization, scope and the priority frontier |
| `crawler/fetch.py` | Fetcher with retries/backoff; httpx transport |
| `crawler/politeness.py` | robots.txt cache, per-host pacing |
| `crawler/extract.py` | Links, JSON-LD and HTML people extraction |
| `crawler/store.py` | SQLite storage and change detection |
| `crawler/crawl.py` | Orchestration and sitemap seeding |
| `crawler/cli.py` | Command line |

## Built with AI-assisted development

Written spec-first with Claude Code: `docs/design.md` came first, then each module was
implemented against tests and reviewed before committing. When the crawl tests caught a
hostname-validation bug, it was fixed in its own commit.
