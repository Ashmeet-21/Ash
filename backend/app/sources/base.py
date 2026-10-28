from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

USER_AGENT = "JobMatch/1.0 (personal job search tool)"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


@dataclass
class JobIn:
    """A posting normalized from any source."""

    source: str
    external_id: str
    title: str
    jd_text: str
    company: str | None = None
    location: str | None = None
    remote: bool = False
    url: str | None = None
    posted_at: datetime | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    extra: dict = field(default_factory=dict)


class SourceError(Exception):
    pass


def client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "header", "footer", "table"}
SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "nav", "form", "button"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1
        elif tag in BLOCK_TAGS and tag != "li":
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    """HTML (possibly entity-escaped, as Greenhouse returns it) to readable text with line structure."""
    if "&lt;" in raw and "<" not in raw:
        raw = html.unescape(raw)
    parser = _TextExtractor()
    parser.feed(raw)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def parse_dt(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
