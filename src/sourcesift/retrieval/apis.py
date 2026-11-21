"""Adapters for sources that answer a query with live data instead of a feed.

Each adapter requests only its own fixed, documented endpoints. The model
supplies a short query that is URL-encoded as a parameter; it never chooses a
host or path. Requests go through the run's ``Fetcher``, so address pinning,
robots rules, byte limits, and the HTTP budget apply as they do to feeds.
"""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from urllib.parse import urlencode

from sourcesift.retrieval.http import Page
from sourcesift.retrieval.parsing import ParsedItem, plain_text, timestamp
from sourcesift.retrieval.urls import RetrievalError

Get = Callable[[str], Awaitable[Page]]
Records = list[tuple[ParsedItem, Page]]
Adapter = Callable[[str, Get, int, datetime | None], Awaitable[Records]]


def _json(page: Page) -> dict[str, object]:
    try:
        data = json.loads(page.body)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise RetrievalError("The data service returned an unexpected response.")
    return data


def _text(value: object, limit: int = 300) -> str:
    """One bounded line from an untrusted field; absent values become empty."""
    return " ".join(str(value).split())[:limit] if value is not None else ""


async def hacker_news(
    query: str, get: Get, limit: int, since: datetime | None
) -> Records:
    """Current front-page stories, or stories matching a query within the window."""
    parameters: dict[str, str | int] = {"hitsPerPage": limit}
    if query.casefold() in {"", "front page", "frontpage", "top", "top stories"}:
        parameters["tags"] = "front_page"
    else:
        parameters |= {"query": query, "tags": "story"}
        if since is not None:
            parameters["numericFilters"] = f"created_at_i>{int(since.timestamp())}"
    page = await get("https://hn.algolia.com/api/v1/search?" + urlencode(parameters))
    hits = _json(page).get("hits")
    records: Records = []
    for hit in hits if isinstance(hits, list) else []:
        if not isinstance(hit, dict) or not str(hit.get("objectID", "")).isdigit():
            continue
        title = _text(hit.get("title"))
        if not title:
            continue
        points = _text(hit.get("points")) or "unknown"
        comments = _text(hit.get("num_comments")) or "unknown"
        details = [f"Hacker News story with {points} points and {comments} comments."]
        if hit.get("url"):
            details.append(f"Submitted link: {_text(hit['url'], 500)}")
        if hit.get("story_text"):
            details.append(plain_text(str(hit["story_text"])))
        records.append(
            (
                ParsedItem(
                    title,
                    f"https://news.ycombinator.com/item?id={hit['objectID']}",
                    "\n".join(details),
                    _text(hit.get("author"), 80) or None,
                    timestamp(_text(hit.get("created_at"), 40) or None),
                ),
                page,
            )
        )
    return records


# Query word -> (title, API path, latest rows to request, columns to keep or all).
_TREASURY: dict[str, tuple[str, str, int, tuple[str, ...] | None]] = {
    "debt": ("Debt to the Penny", "v2/accounting/od/debt_to_penny", 5, None),
    "interest-rates": (
        "Average Interest Rates on US Treasury Securities",
        "v2/accounting/od/avg_interest_rates",
        40,
        None,
    ),
    # About 170 currencies: keep each row to its name and rate.
    "exchange-rates": (
        "Treasury Reporting Rates of Exchange",
        "v1/accounting/od/rates_of_exchange",
        200,
        ("country_currency_desc", "exchange_rate"),
    ),
}
_TREASURY_SKIP = ("src_line_nbr", "record_fiscal_", "record_calendar_")


async def us_treasury(
    query: str, get: Get, limit: int, since: datetime | None
) -> Records:
    """The latest published rows of one named US Treasury fiscal dataset."""
    key = "-".join(query.casefold().replace("_", " ").split())
    if key not in _TREASURY:
        raise RetrievalError(
            "Unknown dataset; the query must be one of: " + ", ".join(_TREASURY) + "."
        )
    title, path, size, columns = _TREASURY[key]
    page = await get(
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
        f"{path}?" + urlencode({"sort": "-record_date", "page[size]": size})
    )
    data = _json(page)
    listed = data.get("data")
    rows = [
        row
        for row in (listed if isinstance(listed, list) else [])
        if isinstance(row, dict)
    ]
    if not rows:
        raise RetrievalError("The dataset returned no rows.")
    meta = data.get("meta")
    labels = meta.get("labels") if isinstance(meta, dict) else None
    labels = labels if isinstance(labels, dict) else {}
    latest = _text(rows[0].get("record_date"), 20)
    if key != "debt":
        # These datasets publish many rows per period; keep the latest period only.
        rows = [row for row in rows if _text(row.get("record_date"), 20) == latest]
    if columns:
        # A fixed name-and-value pair per row needs no repeated column labels.
        lines = [
            ": ".join(_text(row.get(name), 120) for name in columns) for row in rows
        ]
    else:
        lines = [
            "; ".join(
                f"{_text(labels.get(name, name), 80)}: {_text(value, 120)}"
                for name, value in row.items()
                if not name.startswith(_TREASURY_SKIP) and value not in (None, "null")
            )
            for row in rows
        ]
    text = (
        f"{title}, from the US Treasury Fiscal Data API. Latest record date: "
        f"{latest or 'unknown'}. Amounts are as published, in US dollars or percent.\n"
        + "\n".join(lines)
    )
    # The record date is a reporting period, not a publication time, so the item
    # carries no publication date and is not filtered by the request's window.
    return [
        (
            ParsedItem(f"{title} (as of {latest or 'unknown date'})", page.url, text),
            page,
        )
    ]


ADAPTERS: dict[str, Adapter] = {
    "hacker-news": hacker_news,
    "us-treasury": us_treasury,
}
