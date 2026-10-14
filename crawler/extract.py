"""Extract links and people (name, title) from HTML using only the standard library."""

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser

BLOCK_TAGS = {
    "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "span", "td", "th", "figcaption",
    "strong", "b", "em", "small", "a", "section", "article", "dt", "dd", "br",
}
SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}

TITLE_KEYWORDS = re.compile(
    r"\b(ceo|cto|cfo|coo|cmo|cpo|cro|ciso|founder|co-founder|cofounder|president|chair\w*|"
    r"vp|vice president|director|head of|manager|lead|engineer|partner|principal|officer|"
    r"chief|advisor|scientist|designer|architect|counsel|recruiter|analyst|specialist)\b",
    re.IGNORECASE,
)
NAME_WORD = re.compile(r"^[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü'’\-]+\.?$|^[A-Z]\.$")
NAME_PARTICLES = {"de", "del", "la", "van", "von", "da", "di", "le", "y"}
NOT_NAMES = {
    "our team", "meet the team", "leadership", "about us", "contact us", "learn more",
    "read more", "our people", "board of directors", "join us", "view profile",
}


@dataclass(frozen=True)
class Person:
    name: str
    title: str
    method: str  # "jsonld" | "html"
    confidence: float


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" \t\n|•·–—-:,")


def looks_like_name(text: str) -> bool:
    if not 3 <= len(text) <= 60 or text.lower() in NOT_NAMES or TITLE_KEYWORDS.search(text):
        return False
    words = text.split()
    if not 2 <= len(words) <= 5:
        return False
    core = [w for w in words if w.lower() not in NAME_PARTICLES]
    return len(core) >= 2 and all(NAME_WORD.match(w) for w in core)


def looks_like_title(text: str) -> bool:
    return 2 <= len(text) <= 100 and bool(TITLE_KEYWORDS.search(text))


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.blocks: list[str] = []
        self.jsonld: list[str] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._in_jsonld = False

    def _flush(self):
        text = _clean("".join(self._buffer))
        if text:
            self.blocks.append(text)
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "script" and (attrs.get("type") or "").lower() == "application/ld+json":
            self._in_jsonld = True
            self._buffer_jsonld: list[str] = []
            return
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag):
        if tag == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._buffer_jsonld))
            self._in_jsonld = False
            return
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self._in_jsonld:
            self._buffer_jsonld.append(data)
        elif not self._skip_depth:
            self._buffer.append(data)

    def close(self):
        super().close()
        self._flush()


@dataclass
class PageData:
    links: list[str]
    people: list[Person]


def _people_from_jsonld(raw_scripts: list[str]) -> list[Person]:
    found: list[Person] = []

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if "Person" in types and isinstance(node.get("name"), str):
            title = node.get("jobTitle")
            if isinstance(title, list):
                title = ", ".join(t for t in title if isinstance(t, str))
            if isinstance(title, str) and title.strip():
                found.append(Person(_clean(node["name"]), _clean(title), "jsonld", 0.95))
        for key in ("@graph", "employee", "employees", "founder", "founders", "member",
                    "members", "author", "itemListElement", "item"):
            if key in node:
                visit(node[key])

    for raw in raw_scripts:
        try:
            visit(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return found


def _people_from_blocks(blocks: list[str], window: int = 2) -> list[Person]:
    """A name-like block followed within `window` blocks by a title-like block."""
    found: list[Person] = []
    used: set[int] = set()
    for i, block in enumerate(blocks):
        if i in used or not looks_like_name(block):
            continue
        for j in range(i + 1, min(i + 1 + window, len(blocks))):
            if looks_like_name(blocks[j]):
                break  # next person started; this one has no title
            if looks_like_title(blocks[j]):
                found.append(Person(block, blocks[j], "html", 0.7))
                used.update({i, j})
                break
    return found


def name_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def merge_people(people: list[Person]) -> list[Person]:
    """Dedupe by normalized name; the most confident extraction wins."""
    best: dict[str, Person] = {}
    for person in people:
        key = name_key(person.name)
        if key not in best or person.confidence > best[key].confidence:
            best[key] = person
    return sorted(best.values(), key=lambda p: p.name)


def parse_page(html: str) -> PageData:
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    people = merge_people(_people_from_jsonld(parser.jsonld) + _people_from_blocks(parser.blocks))
    return PageData(links=parser.links, people=people)
