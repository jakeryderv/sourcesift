"""Deterministic parser/network fixtures: no publisher or model requests."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

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
    registry = SourceRegistry(BUILTIN_SOURCES)
    assert len(registry.list()) == 8
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
