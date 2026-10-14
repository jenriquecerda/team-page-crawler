# Design: Team Page Crawler

## Problem

Who works at a company, and in what role, is public on most company websites, usually on a
"Team", "About" or "Leadership" page. The data changes as people join, leave and get
promoted. We want a crawler that finds those pages, extracts people and titles, and tells us
what changed since the last crawl, without being a bad citizen on the sites it visits.

## Goals

- Given a list of company domains, find likely team pages within a small page budget.
- Extract `(name, title)` pairs from structured data (schema.org JSON-LD) first, then from
  common HTML "team card" markup.
- Record where every person came from (URL and extraction method).
- Detect changes between crawls: people added, people removed, title changes.
- Be polite: obey robots.txt, identify ourselves, rate-limit per host, back off on 429/5xx.

## Non-goals

- JavaScript rendering. Pages that need a browser are reported, not scraped.
- Logging in, bypassing paywalls, CAPTCHAs or anti-bot measures. If a site says no, we stop.
- Personal contact details (emails, phone numbers). We only keep name, title and source URL.

## Crawl strategy

Per domain: start at `/`, plus `/sitemap.xml` URLs when present. A priority frontier ranks
URLs whose path contains team-ish keywords (`team`, `about`, `leadership`, `people`,
`company`, `management`) above others. We stop at `max_pages` per domain or `max_depth`.
Only same-site HTML pages are followed.

## Politeness

| Rule | Implementation |
| --- | --- |
| robots.txt | Fetched once per host and cached; disallowed URLs are skipped and counted. Missing robots.txt means allowed; a 401/403 on robots.txt means disallow all. |
| Crawl-delay | Honoured when set, otherwise `min_delay` (default 1 s) between requests to a host. |
| Concurrency | Many domains in parallel, but one request at a time per host. |
| Retries | 429 and 5xx are retried with exponential backoff and jitter; `Retry-After` wins when present. 4xx (other than 429) are not retried. |
| Identity | A descriptive User-Agent with a contact URL. |

## Extraction

1. **JSON-LD**: `Person` objects (top level, in `@graph`, or as `employee`/`founder`/`member`
   of an `Organization`) with `name` and `jobTitle`. High confidence.
2. **HTML heuristics**: walk the page's text blocks; a block that looks like a person's name
   followed closely by a block that looks like a job title becomes a candidate. Medium
   confidence. "Looks like a name" is 2–4 capitalised words without title keywords; "looks
   like a title" contains a role keyword (CEO, Engineer, Director, Head of, ...).

Duplicates across pages and methods are merged by normalised name; the higher-confidence
method wins.

## Storage and change detection

SQLite (`sqlite3`, no ORM; one file, easy to inspect). Tables: `pages` (url, status, content
hash, fetched_at) and `people` (domain, name, title, source_url, method, first_seen,
last_seen, active). After each domain crawl, people not seen are marked inactive and a diff
(added / removed / title changed) is returned and printed.

## Risks

- **Heuristic precision**: card layouts vary widely. JSON-LD first, heuristics second, and
  every row records its method so consumers can filter.
- **Unchanged pages re-parsed**: content hashes skip extraction when a page is unchanged.
