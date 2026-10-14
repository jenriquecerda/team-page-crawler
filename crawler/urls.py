"""URL normalization, same-site checks and team-page scoring."""

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

_VALID_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}$|^localhost$")

TEAM_KEYWORDS = ("team", "leadership", "people", "about", "management", "company", "founders")
SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".mp4", ".css", ".js",
    ".xml", ".ico", ".woff", ".woff2",
)


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Absolute, fragment-free, lowercase host, no default port. None if not http(s)."""
    if base:
        url = urljoin(base, url)
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:  # e.g. a non-numeric port
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if not _VALID_HOST.match(host):
        return None
    if port and not (
        (parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = parts.path or "/"
    return urlunsplit((parts.scheme, host, path, parts.query, ""))


def registrable_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def same_site(url: str, root: str) -> bool:
    return registrable_host(url) == registrable_host(root)


def looks_like_html(url: str) -> bool:
    return not urlsplit(url).path.lower().endswith(SKIP_EXTENSIONS)


def team_score(url: str) -> int:
    """Higher means more likely to be a team page. Used as frontier priority."""
    path = urlsplit(url).path.lower()
    score = sum(3 for keyword in TEAM_KEYWORDS if keyword in path)
    if path in ("", "/"):
        score += 1
    return score - path.count("/")  # prefer shallow pages
