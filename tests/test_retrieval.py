"""Deterministic parser/network fixtures: no publisher or model requests."""

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sourcesift import (
    ConfigurationError,
    Limits,
    Settings,
    Source,
    SourceRegistry,
    SourceSift,
    SourcesSettings,
    load_settings,
)
from sourcesift.builtin import (
    BUILTIN_CATALOG,
    builtin_toolkit,
    hacker_news,
    us_treasury,
    weather,
)
from sourcesift.contract import Contract
from sourcesift.data import Figure, StatView, Table, TableView
from sourcesift.extend import Record, SourceResult, Toolkit, source, widget
from sourcesift.retrieval import http
from sourcesift.retrieval.http import Fetcher, Page, public_address
from sourcesift.retrieval.parsing import (
    discover_feeds,
    parse_article,
    parse_feed,
    plain_text,
    timestamp,
)
from sourcesift.retrieval.research import Research, make_window
from sourcesift.retrieval.urls import RetrievalError, normalize_url
from sourcesift.sources import BUILTIN_SOURCES


@pytest.mark.asyncio
async def test_retained_ids_refresh_and_new_evidence_have_per_turn_budgets():
    settings = Settings(limits=Limits(max_items=1))
    fetcher = AsyncMock()
    fetcher.get.return_value = page(feed(entry()))
    first = Research(settings, SourceRegistry([SOURCE]), fetcher, "news", now=NOW)
    await first.research(["fixture"], [], [], "any")
    old = next(iter(first.all_evidence.values()))
    assert old.id == "S1"
    second = Research(
        settings,
        SourceRegistry([SOURCE]),
        fetcher,
        "news",
        now=NOW,
        previous=first.all_evidence,
        next_id=first.next_id,
    )
    fetcher.get.return_value = page(
        feed(
            entry(
                url="https://example.com/new",
                title="New story",
                summary="Different report",
            )
        )
    )
    await second.research(["fixture"], [], [], "any")
    assert len(second.evidence) == 1 and len(second.all_evidence) == 2
    assert (
        second.references("Old [S1] and new [S2]")[1].url == "https://example.com/new"
    )
    third = Research(
        settings,
        SourceRegistry([SOURCE]),
        fetcher,
        "refresh",
        now=NOW,
        previous=second.all_evidence,
        next_id=second.next_id,
    )
    fetcher.get.return_value = page(feed(entry(summary="Updated library report")))
    await third.research(["fixture"], [], [], "any")
    refreshed = third.all_evidence[old.url]
    assert refreshed.id == old.id and "Updated" in refreshed.text
    assert third.next_id == 3 and old.text != refreshed.text


@pytest.mark.asyncio
async def test_retained_article_rechecks_named_source_constraints():
    fetcher = AsyncMock()
    fetcher.get.return_value = page(feed(entry()))
    first = Research(Settings(), SourceRegistry([SOURCE]), fetcher, "news", now=NOW)
    await first.research(["fixture"], [], [], "any")
    second = Research(
        Settings(),
        SourceRegistry([SOURCE]),
        fetcher,
        "Only unknown",
        now=NOW,
        previous=first.all_evidence,
        next_id=first.next_id,
    )
    fetcher.get.reset_mock()
    await second.research([], [], ["Unknown"], "any")
    reply = await second.read_article("https://example.com/story")
    fetcher.get.assert_not_called()
    assert "outside" in str(reply["limitations"])


NOW = datetime(2026, 10, 14, 16, tzinfo=UTC)
SOURCE = Source(
    id="fixture",
    name="Fixture News",
    website="https://example.com/",
    description="US news and technology",
    feeds=("https://example.com/feed",),
    aliases=("Fixture",),
)
ARTICLE = b"""<!doctype html><html><head><title>Fixture report</title>
<meta property="article:published_time" content="2026-10-14T10:00:00Z">
<meta property="article:modified_time" content="2026-10-14T11:00:00Z">
<meta name="author" content="A Reporter"></head><body><article><h1>Fixture report</h1>
<p>The city announced a new public library on Wednesday. The library will provide free books and computer access to all local residents. Construction is planned to begin next spring.</p>
<p>The council approved the proposal at its meeting after a public consultation. Officials said additional details would be published later this year.</p></article></body></html>"""


def page(body, url="https://example.com/feed", content_type="application/rss+xml"):
    return Page(
        url, url, body.encode() if isinstance(body, str) else body, content_type
    )


def feed(*entries):
    return (
        '<rss version="2.0"><channel><title>Fixture News</title><link>https://example.com/</link><description>Tests</description>'
        + "".join(entries)
        + "</channel></rss>"
    )


def entry(
    url="https://example.com/story",
    title="Library approved",
    date="Wed, 14 Oct 2026 10:00:00 GMT",
    summary="The council approved a new library.",
):
    return f"<item><title>{title}</title><link>{url}</link><description>{summary}</description><pubDate>{date}</pubDate></item>"


def research(pages, *, settings=None, sources=(SOURCE,), prompt="check news"):
    fetcher = AsyncMock()

    async def get(url):
        value = pages[url]
        if isinstance(value, Exception):
            raise value
        return value

    fetcher.get.side_effect = get
    return Research(
        settings or Settings(), SourceRegistry(sources), fetcher, prompt, now=NOW
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:secret@example.com/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest",
        "https://localhost/",
        "https://name.local/",
        "https://a.localhost/",
        "https://example.com:8080/",
        "https://example.com/bad\nurl",
        "https://exa\\mple.com",
        "https://example.com:bad/",
        "https:///missing",
        "https://example.com/" + "x" * 4100,
    ],
)
def test_reject_unsafe_urls(url):
    with pytest.raises(RetrievalError):
        normalize_url(url)


def test_url_normalization():
    assert (
        normalize_url(
            "https://EXAMPLE.com:443/a?utm_source=x&q=one+two&fbclid=1#section"
        )
        == "https://example.com/a?q=one+two"
    )
    assert (
        normalize_url("http://[2606:4700:4700::1111]/")
        == "http://[2606:4700:4700::1111]/"
    )
    assert normalize_url("https://example.com:80/") == "https://example.com:80/"


@given(st.text(alphabet=st.characters(whitelist_categories=("L", "N")), max_size=60))
def test_normalization_idempotent(query):
    from urllib.parse import urlencode

    url = "https://example.com/story?" + urlencode({"q": query, "utm_source": "test"})
    assert normalize_url(normalize_url(url)) == normalize_url(url)


def test_registry_settings_and_sdk_registration(tmp_path):
    registry = SourceRegistry(BUILTIN_CATALOG)
    assert len(registry.list()) == 32 and len(BUILTIN_SOURCES) == 29
    # Publishers that refuse article retrieval are registered as summaries only.
    assert {s.id for s in registry.list() if s.capabilities == ("feed",)} == {
        "al-jazeera",
        "lwn",
        "politico",
    }
    # Live data sources are implemented in Python and declare no feeds.
    live = {s.id for s in registry.list() if "query" in s.capabilities}
    assert (
        live
        == {"hacker-news", "us-treasury", "weather"}
        == set(builtin_toolkit().sources)
    )
    assert all(
        s.capabilities == ("query",) and not s.feeds
        for s in registry.list()
        if s.id in live
    )
    for change in (
        {"capabilities": ["query"]},
        {"capabilities": ["query", "feed"]},
        {"capabilities": ["query", "article"], "feeds": []},
    ):
        with pytest.raises(ValidationError):
            SOURCE.model_validate({**SOURCE.model_dump(), **change})
    resolved = registry.resolve("  PBS NEWS HOUR ")
    assert resolved is not None and resolved.id == "pbs"
    assert registry.resolve("missing") is None
    with pytest.raises(ConfigurationError, match="unique"):
        SourceRegistry([SOURCE, SOURCE.model_copy(update={"id": "other"})])
    with pytest.raises(ValidationError):
        SOURCE.model_validate({**SOURCE.model_dump(), "website": "file:///bad"})
    with pytest.raises(ValidationError):
        SOURCE.model_validate({**SOURCE.model_dump(), "capabilities": ["article"]})
    with pytest.raises(ValidationError):
        SourcesSettings(timezone="Nonexistent/Zone")
    with pytest.raises(ValidationError):
        SourcesSettings(timezone="../UTC")
    with pytest.raises(ConfigurationError, match="Disabled"):
        SourceSift(Settings(sources=SourcesSettings(disabled=("typo",))))
    app = SourceSift(Settings(sources=SourcesSettings(disabled=("npr",))))
    assert app.registry.resolve("NPR") is None
    app.register_source(SOURCE)
    assert app.registry.resolve("Fixture") == SOURCE
    with pytest.raises(ConfigurationError):
        app.register_source(SOURCE)
    path = tmp_path / "config.toml"
    path.write_text("""[sources]
disabled=["npr"]
timezone="America/Chicago"
[[sources.custom]]
id="fixture"
name="Fixture News"
website="https://example.com/"
description="US news"
feeds=["https://example.com/feed"]
""")
    assert load_settings(path).sources.custom[0].id == "fixture"


@pytest.mark.parametrize(
    "label,expected",
    [
        ("recent", "2026-10-07T16:00:00+00:00"),
        ("today", "2026-10-14T00:00:00-05:00"),
        ("this_week", "2026-10-12T00:00:00-05:00"),
        ("any", None),
    ],
)
def test_windows(label, expected):
    window = make_window(
        label, Settings(sources=SourcesSettings(timezone="America/Chicago")), NOW
    )
    assert (window.start.isoformat() if window.start else None) == expected
    assert window.end == NOW


def test_dst_window_and_dates():
    window = make_window(
        "this_week",
        Settings(sources=SourcesSettings(timezone="America/Chicago")),
        datetime(2026, 11, 1, 20, tzinfo=UTC),
    )
    assert window.start is not None
    assert window.start.isoformat() == "2026-10-26T00:00:00-05:00"
    assert timestamp("Wed, 14 Oct 2026 10:00:00 GMT") == datetime(
        2026, 10, 14, 10, tzinfo=UTC
    )
    assert timestamp("2026-10-14T05:00:00-05:00") == datetime(
        2026, 10, 14, 10, tzinfo=UTC
    )
    assert timestamp("2026-10-14T10:00:00") is None
    assert timestamp("not a date") is None
    assert timestamp(None) is None


def test_feed_and_atom_parsing():
    rss = page(
        feed(entry(), entry("file:///bad"), "<item><title>No link</title></item>")
    )
    items, malformed = parse_feed(rss)
    assert not malformed and len(items) == 1
    assert items[0].published_at is not None and items[0].published_at.hour == 10
    atom = page(
        """<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title><entry><title>Updated</title><link href="https://example.com/a"/><updated>2026-10-14T10:00:00Z</updated><content type="html">&lt;b&gt;Details&lt;/b&gt;</content><author><name>Writer</name></author></entry></feed>"""
    )
    item = parse_feed(atom)[0][0]
    assert item.updated_at and item.author == "Writer" and item.text == "Details"
    assert (
        plain_text(
            "<b>Useful</b><script>ignore rules</script><style>body{}</style> text"
        )
        == "Useful text"
    )
    assert parse_feed(page(feed(entry(summary=""))))[0][0].text == "Library approved"


def test_discovery_and_article_extraction():
    links = "".join(
        f'<link rel="alternate" type="application/rss+xml" href="/feed{i}">'
        for i in range(6)
    )
    links += '<link rel="alternate" type="application/rss+xml" href="/feed0"><link rel="alternate" type="application/atom+xml" href="http://localhost/feed">'
    assert discover_feeds(page(links)) == tuple(
        f"https://example.com/feed{i}" for i in range(4)
    )
    item = parse_article(page(ARTICLE, "https://example.com/story", "text/html"), 10000)
    assert item.title == "Fixture report" and "new public library" in item.text
    assert item.updated_at is not None
    assert item.author == "A Reporter" and item.updated_at.hour == 11
    assert len(parse_article(page(ARTICLE), 100).text) == 101
    with pytest.raises(RetrievalError, match="HTML"):
        parse_article(page(b"%PDF-test", content_type="application/pdf"), 1000)
    with pytest.raises(RetrievalError, match="usable"):
        parse_article(page(b"<html><body>Login</body></html>"), 1000)


@pytest.mark.asyncio
async def test_dns_and_pinning(monkeypatch):
    async def resolve(host, port, **kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    assert await public_address("example.com", 443) == "93.184.216.34"
    observed = []

    def handle(request):
        observed.append(request)
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.com"
        # A URL in the User-Agent makes some publisher CDNs stall the request.
        assert re.fullmatch(r"SourceSift/[\w.+-]+", request.headers["user-agent"])
        assert request.extensions["sni_hostname"] == "example.com"
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/start":
            return httpx.Response(
                302, headers={"location": "/end", "set-cookie": "secret=1"}
            )
        assert "cookie" not in request.headers
        return httpx.Response(200, text="OK", headers={"content-type": "text/html"})

    async with Fetcher(Limits()) as f:
        await f.client.aclose()
        f.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        result = await f.get("https://example.com/start")
        assert result.requested_url.endswith("/start") and result.url.endswith("/end")
        assert result.body == b"OK" and f.requests == 3
        await f.get("https://example.com/end")
        assert f.requests == 4  # cached robots
    assert f.client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses",
    [[], ["127.0.0.1"], ["93.184.216.34", "10.1.2.3"], ["::1"], ["169.254.169.254"]],
)
async def test_nonpublic_dns(monkeypatch, addresses):
    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(return_value=[(2, 1, 6, "", (value, 443)) for value in addresses]),
    )
    with pytest.raises(RetrievalError, match="Non-public"):
        await public_address("example.com", 443)


@pytest.mark.asyncio
async def test_dns_failure(monkeypatch):
    monkeypatch.setattr(
        asyncio.get_running_loop(), "getaddrinfo", AsyncMock(side_effect=OSError())
    )
    with pytest.raises(RetrievalError, match="resolved"):
        await public_address("example.com", 443)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,match",
    [
        ("redirect", "Redirect limit"),
        ("missing", "no destination"),
        ("private", "public HTTP"),
        ("robots", "robots policy"),
        ("robots503", "HTTP 503"),
        ("status", "HTTP 403"),
        ("large", "byte limit"),
        ("timeout", "timed out"),
        ("http_error", "timed out"),
        ("budget", "request limit"),
    ],
)
async def test_http_failures(monkeypatch, mode, match):
    monkeypatch.setattr(http, "public_address", AsyncMock(return_value="93.184.216.34"))

    async def handle(request):
        if request.url.path == "/robots.txt":
            if mode == "robots":
                return httpx.Response(200, text="User-agent: *\nDisallow: /")
            if mode == "robots503":
                return httpx.Response(503)
            return httpx.Response(410)
        if mode == "redirect":
            return httpx.Response(302, headers={"location": "/loop"})
        if mode == "missing":
            return httpx.Response(302)
        if mode == "private":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/"})
        if mode == "large":
            return httpx.Response(200, content=b"x" * 1025)
        if mode == "timeout":
            await asyncio.sleep(1)
        if mode == "http_error":
            raise httpx.ConnectError("secret internal details")
        return httpx.Response(403)

    async with Fetcher(
        Limits(
            max_response_bytes=1024,
            http_timeout_seconds=0.05,
            max_http_requests=1 if mode == "budget" else 24,
        )
    ) as f:
        await f.client.aclose()
        f.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with pytest.raises(RetrievalError, match=match) as exc:
            await f.get("https://example.com/article")
        assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_research_freshness_dedup_and_provenance():
    rss = feed(
        entry(),
        entry("https://example.com/story?utm_source=again#x"),
        entry("https://example.com/mirror"),
        entry("https://example.com/old", "Old", "Wed, 30 Sep 2026 10:00:00 GMT"),
        entry("https://example.com/future", "Future", "Wed, 14 Oct 2026 20:00:00 GMT"),
        entry("https://example.com/unknown", "Unknown date", "", "A second report."),
    )
    r = research({SOURCE.feeds[0]: page(rss)})
    reply = await r.research(["fixture"], [], [], "today")
    assert len(reply["evidence"]) == 2
    assert r.selected == ["fixture"]
    refs = r.references("First [S2], then [S1], repeat [S2], invented [S99]")
    assert [ref.id for ref in refs] == ["S2", "S1"]
    assert refs[0].published_at is None
    assert (
        refs[1].publisher == "example.com" and refs[1].retrieved_from == SOURCE.feeds[0]
    )
    assert any("outside" in note for note in r.limitations)
    assert any("freshness" in note for note in r.limitations)


@pytest.mark.asyncio
async def test_named_only_unknown_disabled_and_immutable():
    r = research({SOURCE.feeds[0]: page(feed(entry()))})
    await r.research(["fixture"], [], ["Unknown News"])
    assert not r.evidence and not r.selected
    r.fetcher.get.assert_not_called()
    await r.research(["fixture"], [], [])
    assert any("cannot change" in note for note in r.limitations)
    r2 = research(
        {SOURCE.feeds[0]: page(feed(entry()))}, sources=(SOURCE, BUILTIN_SOURCES[0])
    )
    await r2.research(["npr", "missing", "fixture", "fixture"], [], ["Fixture"])
    assert r2.selected == ["fixture"]
    assert any("outside" in note for note in r2.limitations)
    assert any("disabled" in note for note in r2.limitations)


@pytest.mark.asyncio
async def test_partial_failures_and_source_limit():
    second = SOURCE.model_copy(
        update={
            "id": "two",
            "name": "Second",
            "aliases": (),
            "feeds": ("https://example.com/bad",),
        }
    )
    r = research(
        {
            SOURCE.feeds[0]: page(feed(entry())),
            second.feeds[0]: RetrievalError("HTTP 503; content unavailable."),
        },
        sources=(SOURCE, second),
    )
    await r.research(["two", "fixture"], [], [])
    assert len(r.evidence) == 1 and any(
        "Second: HTTP 503" in note for note in r.limitations
    )
    r = research(
        {SOURCE.feeds[0]: page(feed(entry()))},
        sources=(SOURCE, second),
        settings=Settings(limits=Limits(max_sources=1)),
    )
    await r.research(["fixture", "two"], [], [])
    assert len(r.selected) == 1 and any(
        "Source limit" in note for note in r.limitations
    )


@pytest.mark.asyncio
async def test_feed_discovery_errors_and_capabilities():
    nofeeds = SOURCE.model_copy(update={"feeds": ()})
    r = research(
        {
            SOURCE.website: page(
                '<html><link rel="alternate" type="application/rss+xml" href="/feed"></html>'
            ),
            SOURCE.feeds[0]: page(feed(entry())),
        },
        sources=(nofeeds,),
    )
    await r.research(["fixture"], [], [])
    assert len(r.evidence) == 1
    for contents, expected in [
        (page("<html></html>"), "No RSS"),
        (RetrievalError("unavailable"), "unavailable"),
    ]:
        r = research({SOURCE.website: contents}, sources=(nofeeds,))
        await r.research(["fixture"], [], [])
        assert any(expected in note for note in r.limitations)
    r = research(
        {}, sources=(nofeeds.model_copy(update={"capabilities": ("article",)}),)
    )
    await r.research(["fixture"], [], [])
    assert any("does not offer" in note for note in r.limitations)
    r = research({SOURCE.feeds[0]: page("broken XML")})
    await r.research(["fixture"], [], [])
    assert any("malformed" in note for note in r.limitations)
    assert any("no usable entries" in note for note in r.limitations)


@pytest.mark.asyncio
async def test_article_upgrade_and_redirect_provenance():
    article = Page(
        "https://example.com/story",
        "https://other.example/report",
        ARTICLE,
        "text/html",
    )
    r = research(
        {SOURCE.feeds[0]: page(feed(entry())), "https://example.com/story": article}
    )
    await r.research(["fixture"], [], ["Fixture"])
    await r.read_article("https://example.com/story")
    assert len(r.evidence) == 1
    ref = r.references("Supported [S1]")[0]
    assert (
        ref.kind == "article"
        and ref.publisher == "other.example"
        and ref.source_id is None
    )
    assert ref.requested_url == "https://example.com/story"
    assert ref.updated_at.hour == 11
    assert any("different publisher" in note for note in r.limitations)
    assert "new public library" in next(iter(r.evidence.values())).text


@pytest.mark.asyncio
async def test_direct_url_and_article_budgets():
    url = "https://example.com/story"
    r = research(
        {url: page(ARTICLE, url, "text/html")},
        prompt=f"Summarize ({url}). http://localhost/nope",
    )
    await r.read_article(url)
    assert any("research first" in note for note in r.limitations)
    await r.research([], [url, "https://example.com/invented"], [], "any")
    await r.read_article(url)
    assert r.articles == 1 and len(r.evidence) == 1
    assert any("not present" in note for note in r.limitations)
    await r.read_article("https://example.com/invented")
    assert any("outside" in note for note in r.limitations)
    r = research(
        {SOURCE.feeds[0]: page(feed(entry()))},
        settings=Settings(limits=Limits(max_articles=0)),
    )
    await r.research(["fixture"], [url], [])
    await r.read_article(url)
    assert any("Article limit" in note for note in r.limitations)
    r = research({}, prompt=url)
    await r.research([], [url], ["Fixture"])
    assert any("named publication" in note for note in r.limitations)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limits,match",
    [
        (Limits(max_items_per_source=1), "capped"),
        (Limits(max_items=1), "item limit"),
        (Limits(max_evidence_chars=100), "text limit"),
        (Limits(max_item_chars=100), "truncated"),
    ],
)
async def test_evidence_limits(limits, match):
    r = research(
        {
            SOURCE.feeds[0]: page(
                feed(
                    entry(summary="a" * 200),
                    entry("https://example.com/second", "Second", summary="b" * 200),
                )
            )
        },
        settings=Settings(limits=limits),
    )
    await r.research(["fixture"], [], [])
    assert any(match in note for note in r.limitations)
    assert (
        sum(len(item.text) for item in r.evidence.values()) <= limits.max_evidence_chars
    )


@pytest.mark.asyncio
async def test_upgrade_updates_limitations_and_date_conflicts():
    url = "https://example.com/story"
    r = research(
        {
            SOURCE.feeds[0]: page(feed(entry(date=""))),
            url: page(ARTICLE, url, "text/html"),
        }
    )
    await r.research(["fixture"], [], [])
    assert any("freshness" in note for note in r.limitations)
    await r.read_article(url)
    assert not any(
        "freshness" in note or "feed summary" in note for note in r.limitations
    )
    assert r.references("[S1]")[0].kind == "article"
    old = ARTICLE.replace(b"2026-10-14T10:00:00Z", b"2026-09-01T10:00:00Z")
    r = research(
        {SOURCE.feeds[0]: page(feed(entry())), url: page(old, url, "text/html")}
    )
    await r.research(["fixture"], [], [])
    await r.read_article(url)
    assert not r.evidence  # explicit article date corrects the feed's misleading date


@pytest.mark.asyncio
async def test_feed_only_and_update_only_dates():
    r = research(
        {SOURCE.feeds[0]: page(feed(entry()))},
        sources=(SOURCE.model_copy(update={"capabilities": ("feed",)}),),
    )
    await r.research(["fixture"], [], [])
    await r.read_article("https://example.com/story")
    assert any("does not offer article" in note for note in r.limitations)
    atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Updated</title><link href="https://example.com/a"/><updated>2026-10-14T10:00:00Z</updated><summary>Update only</summary></entry></feed>'
    r = research({SOURCE.feeds[0]: page(atom)})
    await r.research(["fixture"], [], [])
    assert any("Only an update date" in note for note in r.limitations)


@pytest.mark.asyncio
async def test_redirect_merge_keeps_unique_citation_ids():
    a, b, c = (f"https://example.com/{suffix}" for suffix in ("a", "b", "c"))
    r = research(
        {
            SOURCE.feeds[0]: page(feed(entry(a, "A"), entry(b, "B"))),
            a: Page(a, b, ARTICLE, "text/html"),
            c: page(
                ARTICLE.replace(b"Fixture report", b"Different report"), c, "text/html"
            ),
        },
        prompt=f"Check news and {c}",
    )
    await r.research(["fixture"], [], [])
    await r.read_article(a)
    await r.read_article(c)
    ids = [item.id for item in r.evidence.values()]
    assert len(ids) == len(set(ids)) == 2
    assert set(ids) == {"S2", "S3"}


@pytest.mark.asyncio
async def test_conversation_cache_reuses_feeds_but_not_articles():
    from dataclasses import replace
    from datetime import timedelta

    from sourcesift.retrieval.http import PageCache

    cache = PageCache(600)
    registry = SourceRegistry([SOURCE])
    fetcher = AsyncMock()
    first_page = page(feed(entry()))
    fetcher.get.return_value = first_page
    first = Research(Settings(), registry, fetcher, "news", now=NOW, cache=cache)
    await first.research(["fixture"], [], [], "any")
    second = Research(Settings(), registry, fetcher, "again", now=NOW, cache=cache)
    await second.research(["fixture"], [], [], "any")
    assert fetcher.get.await_count == 1
    # Reused evidence reports when its bytes were really fetched.
    (item,) = second.evidence.values()
    assert item.retrieved_at == first_page.fetched_at

    # Articles are always retrieved again, even within the cache lifetime.
    url = "https://example.com/story"
    fetcher.get.return_value = page(
        "<html><body><article><h1>Library approved</h1><p>"
        + "The council approved a new library after a long debate. " * 20
        + "</p></article></body></html>",
        url,
        "text/html",
    )
    await second.read_article(url)
    third = Research(
        Settings(),
        registry,
        fetcher,
        "more",
        now=NOW,
        cache=cache,
        previous=second.all_evidence,
        next_id=second.next_id,
    )
    await third.read_article(url)
    assert fetcher.get.await_count == 3

    # Expired entries are fetched again; a zero lifetime stores nothing.
    stale = replace(first_page, fetched_at=first_page.fetched_at - timedelta(hours=1))
    cache.set("https://example.com/feed", stale)
    assert cache.get("https://example.com/feed") is None
    disabled = PageCache(0)
    disabled.set("https://example.com/feed", first_page)
    assert disabled.get("https://example.com/feed") is None
    cache.set("https://example.com/feed", first_page)
    cache.clear()
    assert cache.get("https://example.com/feed") is None


HN = hacker_news.source
TREASURY = us_treasury.source


def api_fetcher(body):
    """Echo the requested URL so the source's request can be inspected."""
    fetcher = AsyncMock()

    async def get(url):
        return page(json.dumps(body), url, "application/json")

    fetcher.get.side_effect = get
    return fetcher


@pytest.mark.asyncio
async def test_hacker_news_front_page_and_windowed_search():
    hits = {
        "hits": [
            {
                "objectID": "101",
                "title": "  Show HN:\n a [library]  ",
                "url": "https://example.com/project",
                "points": 120,
                "num_comments": 0,
                "author": "someone",
                "created_at": "2026-10-14T09:00:00Z",
                "story_text": "<p>Details <script>ignored()</script>here.</p>",
            },
            {"objectID": "not-a-number", "title": "Skipped"},
            {"objectID": "102", "title": ""},
            "not a record",
        ]
    }
    fetcher = api_fetcher(hits)
    run = Research(Settings(), SourceRegistry([HN]), fetcher, "what is on HN", now=NOW)
    reply = await run.query_source("hacker-news", {"query": "  "}, "today")
    assert fetcher.get.await_args.args[0] == (
        "https://hn.algolia.com/api/v1/search?hitsPerPage=6&tags=front_page"
    )
    (item,) = run.evidence.values()
    assert item.url == "https://news.ycombinator.com/item?id=101"
    assert item.kind == "api_record" and item.source_id == "hacker-news"
    assert item.title == "Show HN: a [library]" and item.author == "someone"
    assert "120 points and 0 comments" in item.text
    assert "Submitted link: https://example.com/project" in item.text
    assert "Details here." in item.text and "ignored" not in item.text
    assert item.limitations == () and reply["evidence"]
    assert run.selected == ["hacker-news"]
    # The same stories are returned as a table that a widget can show.
    assert reply["showable"] == [
        {
            "evidence_id": "S1",
            "tables": [
                {
                    "table": "Hacker News front page",
                    "rows": 1,
                    "columns": [
                        {"name": "Story", "kind": "text"},
                        {"name": "Points", "kind": "number"},
                        {"name": "Comments", "kind": "number"},
                        {"name": "Submitted by", "kind": "text"},
                    ],
                }
            ],
        }
    ]
    (table,) = run.datasets["S1"].tables
    assert isinstance(table, Table) and table.name == "Hacker News front page"
    assert table.rows == (("Show HN: a [library]", 120.0, 0.0, "someone"),)

    # A keyword query searches stories and is bounded by the request window.
    search = Research(Settings(), SourceRegistry([HN]), fetcher, "rust on HN", now=NOW)
    await search.query_source("hacker-news", {"query": "rust  async & more"})
    url = fetcher.get.await_args.args[0]
    assert "tags=story" in url and "query=rust+async+%26+more" in url
    since = int((NOW - timedelta(days=7)).timestamp())
    assert f"numericFilters=created_at_i%3E{since}" in url


@pytest.mark.asyncio
async def test_treasury_table_dataset_keeps_the_latest_period():
    body = {
        "data": [
            {
                "record_date": "2026-09-30",
                "security_desc": "Treasury Bills",
                "avg_interest_rate_amt": "4.014",
                "src_line_nbr": "1",
                "record_fiscal_year": "2026",
                "record_calendar_month": "09",
            },
            {
                "record_date": "2026-09-30",
                "security_desc": "Treasury Notes",
                "avg_interest_rate_amt": "3.399",
            },
            {
                "record_date": "2026-08-31",
                "security_desc": "Old Bills",
                "avg_interest_rate_amt": "9.999",
            },
        ],
        "meta": {"labels": {"avg_interest_rate_amt": "Average Interest Rate Amount"}},
    }
    fetcher = api_fetcher(body)
    run = Research(Settings(), SourceRegistry([TREASURY]), fetcher, "rates", now=NOW)
    # A reporting period older than the window is still the latest published value.
    await run.query_source("us-treasury", {"dataset": "interest-rates"}, "today")
    assert fetcher.get.await_args.args[0] == (
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
        "v2/accounting/od/avg_interest_rates?sort=-record_date&page%5Bsize%5D=40"
    )
    (item,) = run.evidence.values()
    assert item.title == (
        "Average Interest Rates on US Treasury Securities (as of 2026-09-30)"
    )
    assert item.kind == "api_record" and item.published_at is None
    assert item.limitations == ()
    assert "Average Interest Rate Amount: 4.014" in item.text
    assert "Treasury Notes" in item.text and "Old Bills" not in item.text
    assert "src_line_nbr" not in item.text and "record_fiscal_year" not in item.text
    (table,) = run.datasets[item.id].tables
    assert isinstance(table, Table)
    assert [c.name for c in table.columns] == ["Name", "Average Interest Rate Amount"]
    assert table.columns[1].unit == "%"
    assert table.rows == (("Treasury Bills", 4.014), ("Treasury Notes", 3.399))

    # Invalid params make no request and are returned for the model to correct.
    unknown = Research(Settings(), SourceRegistry([TREASURY]), fetcher, "x", now=NOW)
    calls = fetcher.get.await_count
    for params in (
        {"dataset": "stock prices"},
        {},
        None,
        {"dataset": "debt", "days": 0},
        {"dataset": "debt", "extra": 1},
    ):
        reply = await unknown.query_source("us-treasury", params)
        assert str(reply["error"]).startswith("Invalid params for us-treasury: ")
    assert "Extra inputs are not permitted" in str(reply["error"])
    rejected = await unknown.query_source("us-treasury", {"dataset": "stock prices"})
    # The message names the field, never the rejected value.
    assert "dataset:" in str(rejected["error"])
    assert "stock prices" not in str(rejected["error"])
    assert fetcher.get.await_count == calls and not unknown.evidence
    assert unknown.selected == [] and "error" not in str(unknown.limitations)


def debt_rows():
    return {
        "data": [
            {
                "record_date": "2026-10-14",
                "tot_pub_debt_out_amt": "38000000000300.50",
                "debt_held_public_amt": "30000000000200.25",
                "intragov_hold_amt": "8000000000100.25",
            },
            {
                "record_date": "2026-10-13",
                "tot_pub_debt_out_amt": "38000000000100.50",
                "debt_held_public_amt": "30000000000100.25",
                "intragov_hold_amt": "null",
            },
            {"record_date": "bad date", "tot_pub_debt_out_amt": "1"},
            {
                "record_date": "2026-10-10",
                "tot_pub_debt_out_amt": "37000000000000.00",
                "debt_held_public_amt": "not a number",
                "intragov_hold_amt": "8000000000000.00",
            },
        ]
    }


@pytest.mark.asyncio
async def test_treasury_debt_history_is_evidence_and_a_table():
    fetcher = api_fetcher(debt_rows())
    run = Research(Settings(), SourceRegistry([TREASURY]), fetcher, "debt", now=NOW)
    reply = await run.query_source("us-treasury", {"dataset": "debt", "days": 90})
    url = fetcher.get.await_args.args[0]
    since = (NOW - timedelta(days=90)).date().isoformat()
    assert "v2/accounting/od/debt_to_penny?" in url
    assert f"filter=record_date%3Agte%3A{since}" in url and "sort=-record_date" in url
    (item,) = run.evidence.values()
    assert item.title == "Debt to the Penny (as of 2026-10-14)"
    assert "2026-10-14: Total public debt outstanding: 38000000000300.50" in item.text
    # The text the model cites states the range the chart will draw.
    assert "3 daily records from 2026-10-10 (37000000000000.00)" in item.text
    assert "to 2026-10-14 (38000000000300.50)" in item.text
    # The model is told each table's columns, which is all it needs to pick a chart.
    assert reply["showable"] == [
        {
            "evidence_id": "S1",
            "tables": [
                {
                    "table": "US public debt, 2026-10-10 to 2026-10-14",
                    "rows": 3,
                    "columns": [
                        {"name": "Date", "kind": "time"},
                        {
                            "name": "Total public debt outstanding",
                            "kind": "number",
                            "unit": "USD",
                        },
                        {
                            "name": "Debt held by the public",
                            "kind": "number",
                            "unit": "USD",
                        },
                        {
                            "name": "Intragovernmental holdings",
                            "kind": "number",
                            "unit": "USD",
                        },
                    ],
                }
            ],
        }
    ]
    dataset = run.datasets["S1"]
    assert dataset.source_id == "us-treasury" and dataset.evidence_ids == ("S1",)
    (table,) = dataset.tables
    # Oldest first; an unusable date is dropped and an unusable value is empty.
    assert table.rows == (
        ("2026-10-10", 37000000000000.0, None, 8000000000000.0),
        ("2026-10-13", 38000000000100.5, 30000000000100.25, None),
        ("2026-10-14", 38000000000300.5, 30000000000200.25, 8000000000100.25),
    )

    empty = Research(
        Settings(),
        SourceRegistry([TREASURY]),
        api_fetcher({"data": [{}]}),
        "x",
        now=NOW,
    )
    await empty.query_source("us-treasury", {"dataset": "debt"})
    assert any("no usable values" in note for note in empty.limitations)


TOTAL = "Total public debt outstanding"


@pytest.mark.asyncio
async def test_show_draws_only_retrieved_data_with_validated_options():
    fetcher = api_fetcher(debt_rows())
    run = Research(Settings(), SourceRegistry([TREASURY]), fetcher, "debt", now=NOW)
    line = {"title": "Debt", "x": "Date", "y": [TOTAL], "log_scale": True}
    assert "No data is attached" in str((await run.show("S1", "chart", line))["error"])
    await run.query_source("us-treasury", {"dataset": "debt"})

    shown = await run.show(" [S1] ", "chart", line)
    assert shown == {
        "shown": "chart",
        "title": "Debt",
        "cite": "Cite [S1] in the answer, or this visual is omitted.",
    }
    (block,) = run.blocks
    assert block.widget == "chart" and block.evidence_ids == ("S1",)
    assert block.source_id == "us-treasury" and len(block.table.rows) == 3
    assert block.options == line | {"kind": "line", "series": ""}
    view: Any = block.view
    assert isinstance(view, Figure) and view.overlay == "none"
    (trace,) = view.data
    assert trace["type"] == "scatter" and trace["mode"] == "lines"
    assert trace["x"] == ["2026-10-10", "2026-10-13", "2026-10-14"]
    assert trace["y"][-1] == 38000000000300.5 and trace["name"] == TOTAL
    assert view.layout["xaxis"] == {"type": "date"}
    assert view.layout["yaxis"] == {"tickprefix": "$", "type": "log"}
    # Showing the same thing twice adds nothing.
    assert "cite" not in await run.show("S1", "chart", line)
    assert len(run.blocks) == 1

    # The model cannot supply values or unknown options.
    for options in (
        {"x": "Date"},
        line | {"data": [1, 2]},
        line | {"title": "x" * 81},
        line | {"kind": "radar"},
    ):
        reply = await run.show("S1", "chart", options)
        assert str(reply["error"]).startswith("Invalid options for chart: ")
    # Options that do not fit the table come back with what would.
    for options, text in (
        (line | {"x": "Day"}, "There is no column 'Day'. Columns: Date, Total"),
        (line | {"y": ["Date"]}, "Column 'Date' is not numeric."),
        (line | {"y": [TOTAL, "Debt held by the public"], "series": "Date"}, "one y"),
        (line | {"kind": "donut", "y": ["Intragovernmental holdings"]}, None),
    ):
        reply = await run.show("S1", "chart", options)
        assert (text or "shown") in str(reply.get("error", reply))
    assert (
        "Unknown widget. Widgets: chart, table, stats, map."
        == (await run.show("S1", "pie"))["error"]
    )
    assert "no latitude column" in str((await run.show("S1", "map"))["error"])
    assert "No table has that name. Tables: US public debt" in str(
        (await run.show("S1", "table", table="Rates"))["error"]
    )
    donut: Any = run.blocks[1].view
    assert len(run.blocks) == 2 and donut.data[0]["type"] == "pie"

    # Several numeric columns become several series, and bars stack.
    await run.show(
        "S1",
        "chart",
        {
            "kind": "stacked_bar",
            "x": "Date",
            "y": ["Debt held by the public", "Intragovernmental holdings"],
        },
    )
    bars: Any = run.blocks[2].view
    assert [t["type"] for t in bars.data] == ["bar", "bar"]
    assert bars.layout["barmode"] == "stack" and bars.layout["showlegend"] is True
    assert bars.data[1]["y"] == [8000000000000.0, None, 8000000000100.25]

    await run.show("S1", "stats", table="us public debt, 2026-10-10 to 2026-10-14")
    figures = run.blocks[3].view
    assert isinstance(figures, StatView)
    assert figures.title == "US public debt, 2026-10-10 to 2026-10-14"
    # The latest row, each with its change from the row before where both exist.
    assert [(i.label, i.value, i.unit, i.change) for i in figures.items] == [
        (TOTAL, 38000000000300.5, "USD", 200.0),
        ("Debt held by the public", 30000000000200.25, "USD", 100.0),
        ("Intragovernmental holdings", 8000000000100.25, "USD", None),
    ]
    # A visual is kept only when the answer cites its evidence.
    assert run.blocks_for("Debt rose [S1].") == tuple(run.blocks)
    assert run.blocks_for("Debt rose [S9].") == () == run.blocks_for("Debt rose.")

    limited = Research(
        Settings(limits=Limits(max_blocks=1)),
        SourceRegistry([TREASURY]),
        fetcher,
        "debt",
        now=NOW,
        datasets=run.datasets,
    )
    # Data from an earlier turn can still be shown, up to the per-answer limit.
    assert (await limited.show("S1", "stats"))["shown"] == "stats"
    assert "limit" in str((await limited.show("S1", "chart", line))["error"])


def test_chart_kinds_follow_the_columns_they_are_given():
    builtin = builtin_toolkit().widgets
    stories = Table(
        name="Stories",
        columns=({"name": "Story"}, {"name": "Points"}, {"name": "Topic"}),
        rows=(("A" * 60, 30, "ai"), ("Short", 10, "web"), (None, 5, "ai")),
    )

    def draw(**options):
        chart = builtin["chart"]
        return chart.render(stories, chart.options.model_validate(options))

    # Named categories are drawn sideways, shortened, with the full name on hover.
    bars = draw(kind="bar", x="Story", y=["Points"])
    (trace,) = bars.data
    assert trace["orientation"] == "h" and trace["x"] == [30.0, 10.0]
    assert trace["y"] == ["A" * 47 + "…", "Short"]
    assert trace["customdata"] == ["A" * 60, "Short"]
    assert bars.layout["yaxis"] == {"type": "category", "autorange": "reversed"}
    assert bars.layout["height"] == 220 and "hovermode" not in bars.layout
    # A text column splits one measure into a series per value.
    split = draw(kind="bar", x="Story", y=["Points"], series="Topic")
    assert [t["name"] for t in split.data] == ["ai", "web"]
    donut = draw(kind="donut", x="Topic", y=["Points"])
    assert donut.data[0]["labels"] == ["ai", "web", "ai"]
    assert donut.data[0]["textinfo"] == "percent" and donut.layout["showlegend"]
    assert donut.data[0]["values"] == [30.0, 10.0, 5.0]
    for options, text in (
        ({"kind": "line", "x": "Story", "y": ["Points"]}, "Use bar for categories"),
        ({"x": "Points", "y": ["Story"]}, "is not numeric"),
    ):
        with pytest.raises(ValueError, match=text):
            draw(**options)
    scatter = draw(kind="scatter", x="Points", y=["Points"])
    assert scatter.data[0]["mode"] == "markers" and "hovermode" not in scatter.layout

    many = Table(
        name="Many",
        columns=({"name": "K"}, {"name": "V", "unit": "%"}),
        rows=tuple((f"k{i}", i) for i in range(70)),
    )
    chart = builtin["chart"]
    for kind in ("bar", "donut"):
        with pytest.raises(ValueError, match="bars|donut"):
            chart.render(many, chart.options.model_validate(
                {"kind": kind, "x": "K", "y": ["V"]}
            ))  # fmt: skip
    picked: Any = builtin["table"].render(
        many, builtin["table"].options.model_validate({"columns": ["V"], "max_rows": 2})
    )
    assert picked.rows == ((0,), (1,)) and picked.columns[0].unit == "%"
    first: Any = builtin["stats"].render(
        many, builtin["stats"].options.model_validate({"row": "first"})
    )
    assert [(i.label, i.value, i.change) for i in first.items] == [("V", 0, None)]
    for bad in (
        Table(name="x", columns=({"name": "a"},), rows=()),
        Table(name="x", columns=({"name": "a"},), rows=(("text",),)),
    ):
        with pytest.raises(ValueError, match="no rows|no values"):
            builtin["stats"].render(bad, builtin["stats"].options())
    with pytest.raises(ValidationError, match="unique"):
        Table(name="x", columns=({"name": "a"}, {"name": "a"}), rows=())


@pytest.mark.asyncio
async def test_widgets_and_sources_are_independent_python_definitions():
    class Params(Contract):
        city: str

    @source(
        id="readings",
        name="Readings",
        website="https://example.com/",
        description="Sensor readings",
        params=Params,
    )
    async def readings(params, context):
        fetched = await context.get("https://example.com/api?city=" + params.city)
        rows = tuple((f"r{i}", i) for i in range(30))
        table = Table(
            name="Readings", columns=({"name": "Id"}, {"name": "Value"}), rows=rows
        )
        return SourceResult(
            [
                Record(
                    "Readings for " + params.city, fetched.url, "30 readings", fetched
                )
            ],
            # Anything that is not a table is ignored rather than shown.
            (table, "not a table"),  # ty: ignore[invalid-argument-type]
        )

    class Options(Contract):
        top: int = 3

    @widget(id="top", description="First rows.", options=Options)
    def top(data, options):
        return TableView(
            title="Top", columns=data.columns, rows=data.rows[: options.top]
        )

    @widget(id="gauge", description="A custom Plotly figure.")
    def gauge(data, options):
        value = data.rows[-1][1]
        return Figure(title="Latest", data=({"type": "indicator", "value": value},))

    @widget(id="broken", description="Fails.")
    def broken(data, options):
        return data.rows[100]

    @widget(id="wrong", description="Returns no view.")
    def wrong(data, options):
        return "not a view"

    @widget(id="picky", description="Explains itself.")
    def picky(data, options):
        raise ValueError("Needs a   Region column.")

    assert readings.source.capabilities == ("query",)
    with pytest.raises(ConfigurationError, match="unique"):
        Toolkit([readings, readings])
    with pytest.raises(ConfigurationError, match="unique"):
        Toolkit(widgets=[top, top])
    builtin = builtin_toolkit()
    toolkit = Toolkit(
        [readings], [*builtin.widgets.values(), top, gauge, broken, wrong, picky]
    )
    fetcher = api_fetcher({})
    run = Research(
        Settings(),
        SourceRegistry([readings.source]),
        fetcher,
        "x",
        now=NOW,
        toolkit=toolkit,
    )
    reply = await run.query_source("readings", {"city": "Oslo"})
    assert reply["showable"] == [
        {
            "evidence_id": "S1",
            "tables": [
                {
                    "table": "Readings",
                    "rows": 30,
                    "columns": [
                        {"name": "Id", "kind": "text"},
                        {"name": "Value", "kind": "number"},
                    ],
                }
            ],
        }
    ]
    # A built-in widget shows a new source's data, and new widgets show it too.
    await run.show("S1", "table", {"max_rows": 2})
    await run.show("S1", "top")
    await run.show("S1", "gauge")
    first, second, third = run.blocks
    assert isinstance(first.view, TableView) and len(first.view.rows) == 2
    assert first.source_id == "readings" and first.table.name == "Readings"
    assert isinstance(second.view, TableView) and second.view.title == "Top"
    assert second.options == {"top": 3} and len(second.view.rows) == 3
    # A widget may return any Plotly figure.
    assert isinstance(third.view, Figure)
    assert third.view.data == ({"type": "indicator", "value": 29},)
    for name in ("broken", "wrong"):
        assert "could not draw" in str((await run.show("S1", name))["error"])
    # A widget's own explanation reaches the model, on one line.
    assert (await run.show("S1", "picky"))["error"] == "Needs a Region column."
    assert len(run.blocks) == 3

    # The same source is not queryable without its implementation.
    plain = Research(
        Settings(), SourceRegistry([readings.source]), fetcher, "x", now=NOW
    )
    await plain.query_source("readings", {"city": "Oslo"})
    assert any("not queryable" in note for note in plain.limitations)


PLACES = {
    "results": [
        {
            "name": "Portland",
            "admin1": "Oregon",
            "country": "United States",
            "country_code": "US",
            "latitude": 45.52,
            "longitude": -122.68,
        },
        {
            "name": "Portland",
            "admin1": "Maine",
            "country": "United States",
            "country_code": "US",
            "latitude": 43.66,
            "longitude": -70.26,
        },
    ]
}
FORECAST = {
    "timezone": "America/New_York",
    "current": {
        "time": 1795237200,
        "temperature_2m": 52.6,
        "apparent_temperature": 47.2,
        "relative_humidity_2m": 65,
        "wind_speed_10m": 7.9,
        "weather_code": 61,
    },
    "hourly": {
        "time": [1795233600, 1795237200, "bad"],
        "temperature_2m": [50.1, 52.6, 1],
        "apparent_temperature": [46.0, None, 1],
    },
    "daily": {
        "time": [1795237200, 1795323600],
        "weather_code": [61, 3],
        "temperature_2m_max": [55.0, 60.5],
        "temperature_2m_min": [41.9, None],
        "precipitation_probability_max": [80, 10],
    },
}


def weather_fetcher(places=PLACES, forecast=FORECAST):
    fetcher = AsyncMock()
    calls = []

    async def get(url, **options):
        calls.append((url, options))
        body = places if "geocoding-api" in url else forecast
        return page(json.dumps(body), url, "application/json")

    fetcher.get.side_effect = get
    return fetcher, calls


@pytest.mark.asyncio
async def test_weather_resolves_a_place_and_returns_four_tables():
    fetcher, calls = weather_fetcher()
    run = Research(
        Settings(limits=Limits(max_blocks=6)),
        SourceRegistry([weather.source]),
        fetcher,
        "x",
        now=NOW,
    )
    reply: Any = await run.query_source(
        "weather", {"place": "Portland, Maine", "units": "imperial", "days": 2}
    )
    (geocode, _), (forecast, _) = calls
    assert geocode.startswith(
        "https://geocoding-api.open-meteo.com/v1/search?name=Portland&"
    )
    # The qualifier picks Maine over the first, larger match.
    assert "latitude=43.66" in forecast and "longitude=-70.26" in forecast
    assert "temperature_unit=fahrenheit" in forecast and "forecast_days=2" in forecast
    # Only this source's declared API hosts skip the robots check.
    assert all(options == {"robots": False} for _, options in calls)
    (item,) = run.evidence.values()
    assert item.title.startswith("Weather for Portland, Maine, United States (")
    assert item.kind == "api_record" and item.limitations == ()
    assert (
        "Now: Light rain. Temperature: 52.6°F; Feels like: 47.2°F; Humidity: 65%"
        in item.text
    )
    assert "Wind: 7.9 mph" in item.text
    assert "Light rain, 55.0°F / 41.9°F, 80.0%" in item.text
    assert "Overcast, 60.5°F / ?°F, 10.0%" in item.text
    assert "not an official warning" in item.text
    place = "Portland, Maine, United States"
    (showable,) = reply["showable"]
    assert [t["table"] for t in showable["tables"]] == [
        f"Weather now in {place}: Light rain",
        f"Location of {place}",
        f"Hourly temperature in {place}",
        f"Daily forecast for {place}",
    ]
    assert showable["tables"][2]["columns"][0] == {"name": "Time", "kind": "time"}
    now, located, hourly, daily = run.datasets["S1"].tables
    assert [(c.name, c.unit) for c in now.columns] == [
        ("Temperature", "°F"),
        ("Feels like", "°F"),
        ("Humidity", "%"),
        ("Wind", "mph"),
        ("High today", "°F"),
        ("Low today", "°F"),
    ]
    assert now.rows == ((52.6, 47.2, 65.0, 7.9, 55.0, 41.9),)
    assert located.rows == ((place, 43.66, -70.26, 52.6),)
    # Times are written in the place's own zone; unusable ones are dropped.
    zone = ZoneInfo("America/New_York")
    local = [
        datetime.fromtimestamp(seconds, zone)
        .replace(tzinfo=None)
        .isoformat(timespec="minutes")
        for seconds in (1795233600, 1795237200)
    ]
    assert hourly.rows == ((local[0], 50.1, 46.0), (local[1], 52.6, None))
    assert daily.rows[1] == ("2026-11-22", "Overcast", 60.5, None, 10.0)

    # Without a table name, each widget draws the first table its options fit.
    await run.show("S1", "map", {"overlay": "radar", "zoom": 9, "value": "Temperature"})
    await run.show("S1", "chart", {"x": "Time", "y": ["Temperature", "Feels like"]})
    await run.show("S1", "stats")
    await run.show("S1", "table", table=f"daily forecast for  {place.upper()}")
    views: Any = [block.view for block in run.blocks]
    placed, lines, figures, forecast_table = views
    assert isinstance(placed, Figure) and placed.overlay == "radar"
    assert run.blocks[0].table is located
    (marker,) = placed.data
    assert marker["type"] == "scattermap" and marker["mode"] == "markers+text"
    assert (marker["lat"], marker["lon"]) == ([43.66], [-70.26])
    assert marker["text"] == [f"{place} · 52.6°F"]
    # Radar imagery stops at a regional scale, so the map opens no closer.
    assert placed.layout["map"] == {
        "center": {"lat": 43.66, "lon": -70.26},
        "zoom": 6,
    }
    assert [t["name"] for t in lines.data] == ["Temperature", "Feels like"]
    assert lines.layout["yaxis"] == {"ticksuffix": "°F"}
    assert lines.layout["hovermode"] == "x unified"
    assert [i.label for i in figures.items][:2] == ["Temperature", "Feels like"]
    assert len(figures.items) == 6 and figures.items[0].change is None
    assert isinstance(forecast_table, TableView) and len(forecast_table.rows) == 2
    assert forecast_table.columns[0].kind == "time"
    assert "Invalid options" in str(
        (await run.show("S1", "map", {"zoom": 20}))["error"]
    )
    plain = await run.show("S1", "map", {"zoom": 9})
    closer: Any = run.blocks[-1].view
    assert plain["shown"] == "map" and closer.layout["map"]["zoom"] == 9

    # An unknown qualifier falls back to the best match; no match is reported.
    other, calls = weather_fetcher()
    fallback = Research(
        Settings(), SourceRegistry([weather.source]), other, "x", now=NOW
    )
    await fallback.query_source("weather", {"place": "Portland, Atlantis"})
    assert "latitude=45.52" in calls[1][0] and "temperature_unit=celsius" in calls[1][0]
    for places_body, forecast_body, text in (
        ({"results": []}, FORECAST, "No place with that name"),
        (PLACES, {"current": {}}, "no current conditions"),
    ):
        broken, _ = weather_fetcher(places_body, forecast_body)
        failed = Research(
            Settings(), SourceRegistry([weather.source]), broken, "x", now=NOW
        )
        await failed.query_source("weather", {"place": "Nowhere"})
        assert any(text in note for note in failed.limitations) and not failed.datasets


@pytest.mark.asyncio
async def test_query_source_constraints_and_failures():
    registry = SourceRegistry([SOURCE, HN, TREASURY])
    fetcher = api_fetcher({"hits": []})

    run = Research(Settings(), registry, fetcher, "news", now=NOW)
    await run.query_source("fixture", {})
    await run.query_source("missing", {})
    assert fetcher.get.await_count == 0
    assert any("not queryable" in note for note in run.limitations)
    reply = await run.query_source("hacker-news")
    assert any("returned no records" in note for note in run.limitations)
    assert "showable" not in reply and not run.datasets

    # A feed request for a queryable source explains which tool applies.
    feeds = Research(Settings(), registry, fetcher, "news", now=NOW)
    await feeds.research(["hacker-news"], [], [], "recent")
    assert any("query_source" in note for note in feeds.limitations)

    # A named-publication constraint set by research stays in force.
    named = Research(Settings(), registry, fetcher, "only fixture", now=NOW)
    fetcher.get.side_effect = None
    fetcher.get.return_value = page(feed(entry()))
    await named.research(["fixture"], [], ["Fixture News"], "any")
    count = fetcher.get.await_count
    await named.query_source("hacker-news")
    assert fetcher.get.await_count == count and named.selected == ["fixture"]
    assert named.window is not None and named.window.label == "any"

    limited = Research(
        Settings(limits=Limits(max_sources=1)), registry, api_fetcher({}), "x", now=NOW
    )
    await limited.query_source("hacker-news")
    await limited.query_source("us-treasury", {"dataset": "debt"})
    assert limited.selected == ["hacker-news"]
    assert any("Source limit reached" in note for note in limited.limitations)

    for body in ("not json", "[1, 2]"):
        broken = AsyncMock()
        broken.get.return_value = page(body, "https://hn.algolia.com/x", "text/plain")
        failed = Research(Settings(), registry, broken, "x", now=NOW)
        await failed.query_source("hacker-news")
        assert any("unexpected response" in note for note in failed.limitations)


def test_import_does_not_warn_about_optional_socks_support():
    import subprocess
    import sys

    script = (
        "import urllib3\n"
        # Some optional packages silence urllib3 warnings as a side effect; a
        # plain install has none of them, so take that side effect away.
        "urllib3.disable_warnings = lambda *args, **kwargs: None\n"
        "import sourcesift.cli\n"
    )
    done = subprocess.run(
        [sys.executable, "-W", "always", "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "SOCKS support" not in done.stderr
