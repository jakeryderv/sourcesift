"""Source records and an immutable per-application catalog; no plugin discovery."""

from collections.abc import Iterable
from typing import Literal

from pydantic import Field, field_validator, model_validator

from sourcesift.errors import ConfigurationError
from sourcesift.models import Contract
from sourcesift.retrieval.urls import RetrievalError, normalize_url


class Source(Contract):
    """Publication metadata used for semantic selection, not keyword routing.

    Feed access means recent entries only. A website without feeds uses bounded
    RSS/Atom discovery; article access does not imply search or archive access.
    """

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    website: str
    description: str = Field(min_length=1, max_length=1200)
    feeds: tuple[str, ...] = Field(default=(), max_length=4)
    topics: tuple[str, ...] = Field(default=(), max_length=12)
    geography: str = Field(default="Unspecified", max_length=200)
    language: str = "en"
    aliases: tuple[str, ...] = Field(default=(), max_length=8)
    capabilities: tuple[Literal["feed", "article"], ...] = ("feed", "article")

    @field_validator("website")
    @classmethod
    def valid_website(cls, value: str) -> str:
        try:
            return normalize_url(value)
        except RetrievalError as exc:
            raise ValueError(str(exc)) from None

    @field_validator("feeds")
    @classmethod
    def valid_feeds(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(cls.valid_website(value) for value in values)

    @model_validator(mode="after")
    def consistent_capabilities(self) -> "Source":
        if self.feeds and "feed" not in self.capabilities:
            raise ValueError("feed URLs require the feed capability")
        return self


class SourceRegistry:
    """Validated catalog. Duplicate IDs, names, or aliases fail explicitly."""

    def __init__(self, sources: Iterable[Source]) -> None:
        self._sources: dict[str, Source] = {}
        self._names: dict[str, str] = {}
        for source in sources:
            keys = {
                value.casefold().strip()
                for value in (source.id, source.name, *source.aliases)
            }
            if source.id in self._sources or any(key in self._names for key in keys):
                raise ConfigurationError(
                    "Source IDs, names, and aliases must be unique."
                )
            self._sources[source.id] = source
            self._names.update(dict.fromkeys(keys, source.id))

    def list(self) -> tuple[Source, ...]:
        """Return enabled definitions in registration order."""
        return tuple(self._sources.values())

    def resolve(self, name: str) -> Source | None:
        """Resolve a known ID/name/alias; never silently substitute a publication."""
        key = self._names.get(name.casefold().strip())
        return self._sources.get(key) if key else None


BUILTIN_SOURCES = (
    Source(
        id="npr",
        name="NPR",
        website="https://www.npr.org/",
        feeds=("https://feeds.npr.org/1001/rss.xml",),
        description="General news for a US audience: national affairs, politics, society, and major international developments. Select for a general US news briefing.",
        topics=("news", "politics"),
        geography="US national focus; also international reporting",
    ),
    Source(
        id="pbs",
        name="PBS NewsHour",
        website="https://www.pbs.org/newshour/",
        feeds=("https://www.pbs.org/newshour/feeds/rss/headlines",),
        aliases=("PBS", "PBS News Hour"),
        description="US national public-interest news, politics, policy, and major world stories. Complements NPR for general news.",
        topics=("news", "politics", "business"),
        geography="US national focus; also international reporting",
    ),
    Source(
        id="ars-technica",
        name="Ars Technica",
        website="https://arstechnica.com/",
        feeds=("https://feeds.arstechnica.com/arstechnica/index",),
        aliases=("Ars",),
        description="Technology, software, computing, science, security, and AI developments for technically interested readers.",
        topics=("technology", "ai", "science"),
        geography="US-based; international technology coverage",
    ),
    Source(
        id="techcrunch",
        name="TechCrunch",
        website="https://techcrunch.com/",
        feeds=("https://techcrunch.com/feed/",),
        description="Technology businesses, startups, venture capital, software products, and commercial AI developments.",
        topics=("technology", "ai", "business"),
        geography="US-based; international startup coverage",
    ),
    Source(
        id="mit-technology-review",
        name="MIT Technology Review",
        website="https://www.technologyreview.com/",
        feeds=("https://www.technologyreview.com/feed/",),
        aliases=("MIT Tech Review",),
        description="Emerging technology, artificial intelligence research and impacts, and technology policy. Some articles require a subscription; feed summaries may be all that is available.",
        topics=("technology", "ai"),
        geography="International technology coverage",
    ),
    Source(
        id="marketing-dive",
        name="Marketing Dive",
        website="https://www.marketingdive.com/",
        feeds=("https://www.marketingdive.com/feeds/news/",),
        description="Marketing and advertising industry news: brands, campaigns, agencies, advertising technology, and business strategy.",
        topics=("marketing", "business"),
        geography="US industry focus",
    ),
    Source(
        id="federal-reserve",
        name="Federal Reserve",
        website="https://www.federalreserve.gov/",
        feeds=("https://www.federalreserve.gov/feeds/press_all.xml",),
        aliases=("Fed",),
        description="Official US central bank press releases on monetary policy, banking regulation, and financial-system actions. Primary policy evidence, not a general market news service.",
        topics=("finance", "economics"),
        geography="United States",
    ),
    Source(
        id="cnbc",
        name="CNBC",
        website="https://www.cnbc.com/",
        feeds=("https://www.cnbc.com/id/100003114/device/rss/rss.html",),
        description="Business, financial markets, companies, and economic news for a US audience. Recent top stories; no historical market data or investment recommendations.",
        topics=("business", "finance", "economics"),
        geography="US focus; global markets",
    ),
)
