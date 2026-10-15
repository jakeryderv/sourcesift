"""Pure feed/HTML parsing of already bounded bytes; no hidden network access."""

import html
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

import feedparser
from trafilatura import extract

from sourcesift.retrieval.http import Page
from sourcesift.retrieval.urls import RetrievalError, normalize_url


class _HTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.feeds: list[str] = []
        self.meta: dict[str, str] = {}
        self.title: list[str] = []
        self.in_title = False
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        if (
            tag == "link"
            and "alternate" in (values.get("rel") or "").lower().split()
            and values.get("type")
            in {
                "application/rss+xml",
                "application/atom+xml",
            }
            and values.get("href")
        ):
            self.feeds.append(values["href"] or "")
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta[key.lower()] = values["content"] or ""

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.text.append(data)
            if self.in_title:
                self.title.append(data)


def plain_text(value: str) -> str:
    """Strip markup, executable text, and excess whitespace from feed fields."""
    parser = _HTML()
    parser.feed(value)
    return " ".join(" ".join(parser.text).split())


def timestamp(value: str | None) -> datetime | None:
    """Preserve unknown/zone-less timestamps rather than guessing their zone."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


@dataclass(frozen=True)
class ParsedItem:
    """Adapter output before per-run freshness, deduplication, and citation IDs."""

    title: str
    url: str
    text: str
    author: str | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None


def parse_feed(page: Page) -> tuple[list[ParsedItem], bool]:
    """Parse RSS/Atom entries; caller bounds and filters the returned items."""
    parsed = feedparser.parse(page.body)
    items = []
    for entry in parsed.entries[:200]:
        try:
            url = normalize_url(urljoin(page.url, entry.get("link", "")))
        except RetrievalError:
            continue
        if not entry.get("link"):
            continue

        title = plain_text(entry.get("title", "Untitled"))[:512]
        text = plain_text(entry.get("summary", ""))
        if not text and entry.get("content"):
            text = plain_text(entry.content[0].get("value", ""))
        items.append(
            ParsedItem(
                title,
                url,
                text or title,
                plain_text(entry.get("author", ""))[:256] or None,
                timestamp(entry.get("published")),
                timestamp(entry.get("updated") if "updated" in entry else None),
            )
        )
    return items, bool(parsed.get("bozo"))


def discover_feeds(page: Page) -> tuple[str, ...]:
    """Discover at most four unique declared RSS/Atom URLs from an HTML page."""
    parser = _HTML()
    parser.feed(page.body.decode("utf-8", errors="replace"))
    urls: list[str] = []
    for link in parser.feeds:
        try:
            url = normalize_url(urljoin(page.url, html.unescape(link)))
        except RetrievalError:
            continue
        if url not in urls:
            urls.append(url)
    return tuple(urls[:4])


def parse_article(page: Page, max_chars: int) -> ParsedItem:
    """Extract main HTML text and explicit metadata, without crawling or date guesses."""
    if (
        "html" not in page.content_type.lower()
        and not page.body.lstrip().lower().startswith((b"<!doctype html", b"<html"))
    ):
        raise RetrievalError("Article is not an HTML document.")
    parser = _HTML()
    parser.feed(page.body.decode("utf-8", errors="replace"))
    text = extract(
        page.body,
        url=page.url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text or len(text.strip()) < 80:
        raise RetrievalError(
            "No usable article text; the page may require login or JavaScript."
        )
    title = parser.meta.get("og:title") or " ".join(parser.title) or "Untitled article"
    return ParsedItem(
        plain_text(title)[:512],
        page.url,
        text[: max_chars + 1],
        plain_text(parser.meta.get("author", ""))[:256] or None,
        timestamp(
            parser.meta.get("article:published_time")
            or parser.meta.get("datepublished")
        ),
        timestamp(
            parser.meta.get("article:modified_time") or parser.meta.get("datemodified")
        ),
    )
