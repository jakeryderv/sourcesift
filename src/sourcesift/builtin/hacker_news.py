"""Hacker News stories through the public Algolia search API."""

from urllib.parse import urlencode

from pydantic import Field

from sourcesift.builtin.common import json_object, number, one_line
from sourcesift.contract import Contract
from sourcesift.data import Cell, Column, Table
from sourcesift.extend import FetchContext, Record, SourceResult, source
from sourcesift.retrieval.parsing import plain_text, timestamp

_FRONT_PAGE = {"", "front page", "frontpage", "top", "top stories"}


class HackerNewsParams(Contract):
    """What to look up on Hacker News."""

    query: str = Field(
        default="",
        max_length=200,
        description="Keywords to find stories about a topic within the date window. "
        "Leave empty for the current front page.",
    )


@source(
    id="hacker-news",
    name="Hacker News",
    website="https://news.ycombinator.com/",
    aliases=("HN",),
    description="Live data on what the technology community is discussing: story "
    "titles, points, comment counts, and submitted links. Points and comments "
    "measure attention, not accuracy.",
    topics=("technology", "software", "startups"),
    geography="International technology community",
    params=HackerNewsParams,
)
async def hacker_news(params: HackerNewsParams, context: FetchContext) -> SourceResult:
    """Current front-page stories, or stories matching a query within the window."""
    query = " ".join(params.query.split())
    parameters: dict[str, str | int] = {"hitsPerPage": context.limit}
    if query.casefold() in _FRONT_PAGE:
        parameters["tags"] = "front_page"
    else:
        parameters |= {"query": query, "tags": "story"}
        if context.since is not None:
            parameters["numericFilters"] = (
                f"created_at_i>{int(context.since.timestamp())}"
            )
    page = await context.get(
        "https://hn.algolia.com/api/v1/search?" + urlencode(parameters)
    )
    hits = json_object(page).get("hits")
    records: list[Record] = []
    rows: list[tuple[Cell, ...]] = []
    for hit in hits if isinstance(hits, list) else []:
        if not isinstance(hit, dict) or not str(hit.get("objectID", "")).isdigit():
            continue
        title = one_line(hit.get("title"))
        if not title:
            continue
        points = one_line(hit.get("points")) or "unknown"
        comments = one_line(hit.get("num_comments")) or "unknown"
        details = [f"Hacker News story with {points} points and {comments} comments."]
        if hit.get("url"):
            details.append(f"Submitted link: {one_line(hit['url'], 500)}")
        if hit.get("story_text"):
            details.append(plain_text(str(hit["story_text"])))
        author = one_line(hit.get("author"), 80) or None
        records.append(
            Record(
                title,
                f"https://news.ycombinator.com/item?id={hit['objectID']}",
                "\n".join(details),
                page,
                author,
                timestamp(one_line(hit.get("created_at"), 40) or None),
            )
        )
        rows.append(
            (
                title,
                number(hit.get("points")),
                number(hit.get("num_comments")),
                author,
            )
        )
    if not rows:
        return SourceResult(records)
    table = Table(
        name="Hacker News front page"
        if "tags" in parameters and "query" not in parameters
        else f"Hacker News stories: {query}"[:120],
        columns=(
            Column(name="Story"),
            Column(name="Points"),
            Column(name="Comments"),
            Column(name="Submitted by"),
        ),
        rows=tuple(rows),
    )
    return SourceResult(records, (table,))
