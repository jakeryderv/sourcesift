"""Define typed data sources in Python.

This interface is new and may change. Built-in data sources are defined with
the same decorator. Extensions are trusted Python: unlike the model, they
can do anything the process can.
"""

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from sourcesift.data import Table
from sourcesift.errors import ConfigurationError
from sourcesift.retrieval.http import Page
from sourcesift.retrieval.urls import hostname
from sourcesift.sources import Source


@dataclass(frozen=True)
class Record:
    """Text for the model to read and cite, with the page it was read from."""

    title: str
    url: str
    text: str
    page: Page
    author: str | None = None
    published_at: datetime | None = None


@dataclass(frozen=True)
class SourceResult:
    """One fetch: evidence to cite and, optionally, the same data as tables."""

    evidence: Sequence[Record]
    tables: Sequence[Table] = ()


@dataclass(frozen=True)
class FetchContext:
    """All a source may use: the bounded fetcher, the clock, and the request's limits."""

    get: Callable[[str], Awaitable[Page]]
    now: datetime
    since: datetime | None
    limit: int


Fetch = Callable[[Any, FetchContext], Awaitable[SourceResult]]


@dataclass(frozen=True)
class DataSource:
    """A catalog entry plus the typed function that fetches its data."""

    source: Source
    params: type[BaseModel]
    fetch: Fetch
    api_hosts: tuple[str, ...] = ()

    def bounded(
        self, get: Callable[..., Awaitable[Page]]
    ) -> Callable[[str], Awaitable[Page]]:
        """The fetcher's ``get`` as this source may use it.

        A robots.txt file addresses crawlers, and some public data APIs disallow
        all of them while documenting the API for programs. Requests to a host
        this source declares in ``api_hosts`` skip that one check. Address
        checks, size limits, timeouts, and the request budget always apply.
        """

        async def bounded_get(url: str) -> Page:
            if hostname(url) in self.api_hosts:
                return await get(url, robots=False)
            return await get(url)

        return bounded_get


def source(
    *,
    id: str,
    name: str,
    website: str,
    description: str,
    params: type[BaseModel],
    topics: tuple[str, ...] = (),
    geography: str = "Unspecified",
    aliases: tuple[str, ...] = (),
    api_hosts: tuple[str, ...] = (),
) -> Callable[[Fetch], DataSource]:
    """Turn ``async def fetch(params, context) -> SourceResult`` into a data source.

    ``params`` is validated before the function runs; its field descriptions are
    what the model sees. ``api_hosts`` names hosts of documented public APIs whose robots.txt is not
    consulted; list one only when the service's terms allow programmatic use.
    """
    entry = Source(
        id=id,
        name=name,
        website=website,
        description=description,
        topics=topics,
        geography=geography,
        aliases=aliases,
        capabilities=("query",),
    )
    return lambda fetch: DataSource(entry, params, fetch, api_hosts)


class Toolkit:
    """The data sources available to an application."""

    def __init__(self, sources: Iterable[DataSource] = ()) -> None:
        self.sources: dict[str, DataSource] = {}
        for item in sources:
            if item.source.id in self.sources:
                raise ConfigurationError("Data source IDs must be unique.")
            self.sources[item.source.id] = item
