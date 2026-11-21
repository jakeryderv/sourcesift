"""Source records and an immutable per-application catalog; no plugin discovery."""

from collections.abc import Iterable
from typing import Literal

from pydantic import Field, field_validator, model_validator

from sourcesift.errors import ConfigurationError
from sourcesift.models import Contract
from sourcesift.retrieval.urls import RetrievalError, normalize_url


class Source(Contract):
    """Source metadata used for semantic selection, not keyword routing.

    Feed access means recent entries only. A website without feeds uses bounded
    RSS/Atom discovery; article access does not imply search or archive access.
    A source with the ``query`` capability is a live data service implemented in
    Python (see ``sourcesift.extend``); it has no feed and is not read as articles.
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
    capabilities: tuple[Literal["feed", "article", "query"], ...] = ("feed", "article")

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
        if "query" in self.capabilities and (
            self.feeds or self.capabilities != ("query",)
        ):
            raise ValueError("a live data source has only the query capability")
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
    Source(
        id="bbc-news",
        name="BBC News",
        website="https://www.bbc.com/news",
        feeds=("https://feeds.bbci.co.uk/news/world/rss.xml",),
        aliases=("BBC",),
        description="World news from the UK public broadcaster: international affairs, conflicts, diplomacy, and major events outside the US. Select for world or non-US news.",
        topics=("news", "world", "politics"),
        geography="International; UK-based",
    ),
    Source(
        id="the-guardian",
        name="The Guardian",
        website="https://www.theguardian.com/world",
        feeds=("https://www.theguardian.com/world/rss",),
        aliases=("Guardian",),
        description="International news and analysis: world affairs, politics, climate, and human rights. Complements BBC News for world coverage.",
        topics=("news", "world", "politics", "climate"),
        geography="International; UK-based",
    ),
    Source(
        id="dw",
        name="Deutsche Welle",
        website="https://www.dw.com/en/",
        feeds=("https://rss.dw.com/rdf/rss-en-all",),
        aliases=("DW",),
        description="English-language international news from Germany's public broadcaster, strong on Europe, Africa, and Asia.",
        topics=("news", "world"),
        geography="International; Germany-based",
    ),
    Source(
        id="al-jazeera",
        name="Al Jazeera",
        website="https://www.aljazeera.com/",
        feeds=("https://www.aljazeera.com/xml/rss/all.xml",),
        description="International news with strong Middle East, Africa, and Global South coverage. Feed summaries only: the publisher does not allow article retrieval.",
        topics=("news", "world"),
        geography="International; Qatar-based",
        capabilities=("feed",),
    ),
    Source(
        id="sciencedaily",
        name="ScienceDaily",
        website="https://www.sciencedaily.com/",
        feeds=("https://www.sciencedaily.com/rss/all.xml",),
        aliases=("Science Daily",),
        description="Summaries of new research across science, health, environment, and technology, based on university and journal press releases rather than independent reporting.",
        topics=("science", "health", "research"),
        geography="International research coverage",
    ),
    Source(
        id="quanta-magazine",
        name="Quanta Magazine",
        website="https://www.quantamagazine.org/",
        feeds=("https://www.quantamagazine.org/feed/",),
        aliases=("Quanta",),
        description="In-depth explanatory journalism on mathematics, physics, biology, and computer science research. Publishes a few long articles a week.",
        topics=("science", "mathematics", "research"),
        geography="International research coverage",
    ),
    Source(
        id="nasa",
        name="NASA",
        website="https://www.nasa.gov/",
        feeds=("https://www.nasa.gov/news-release/feed/",),
        description="Official NASA news releases on missions, launches, space science, and agency announcements. Primary agency statements, not independent reporting.",
        topics=("science", "space"),
        geography="United States",
    ),
    Source(
        id="stat-news",
        name="STAT",
        website="https://www.statnews.com/",
        feeds=("https://www.statnews.com/feed/",),
        aliases=("STAT News",),
        description="Health, medicine, biotech, and pharmaceutical industry reporting. Many articles require a subscription; feed summaries may be all that is available.",
        topics=("health", "medicine", "biotech"),
        geography="US focus",
    ),
    Source(
        id="kff-health-news",
        name="KFF Health News",
        website="https://kffhealthnews.org/",
        feeds=("https://kffhealthnews.org/feed/",),
        aliases=("KFF", "Kaiser Health News"),
        description="US health policy, insurance, public health, and healthcare costs from a nonprofit newsroom.",
        topics=("health", "policy"),
        geography="United States",
    ),
    Source(
        id="the-verge",
        name="The Verge",
        website="https://www.theverge.com/",
        feeds=("https://www.theverge.com/rss/index.xml",),
        aliases=("Verge",),
        description="Consumer technology, gadgets, platforms, and the technology industry, with product news and reviews.",
        topics=("technology", "ai", "consumer-tech"),
        geography="US-based; international technology coverage",
    ),
    Source(
        id="wired",
        name="WIRED",
        website="https://www.wired.com/",
        feeds=("https://www.wired.com/feed/rss",),
        description="Technology and its effects on culture, business, security, and science, including longer features.",
        topics=("technology", "ai", "security", "science"),
        geography="US-based; international technology coverage",
    ),
    Source(
        id="github-blog",
        name="GitHub Blog",
        website="https://github.blog/",
        feeds=("https://github.blog/feed/",),
        description="Official GitHub posts on developer tools, product changes, open source, and software security. Primary company announcements.",
        topics=("technology", "software", "open-source"),
        geography="International developer audience",
    ),
    Source(
        id="lwn",
        name="LWN.net",
        website="https://lwn.net/",
        feeds=("https://lwn.net/headlines/rss",),
        aliases=("LWN", "Linux Weekly News"),
        description="Linux kernel, free software, and open-source community news for a technical audience. Feed summaries only: article retrieval is not available.",
        topics=("technology", "linux", "open-source"),
        geography="International developer audience",
        capabilities=("feed",),
    ),
    Source(
        id="politico",
        name="Politico",
        website="https://www.politico.com/",
        feeds=("https://rss.politico.com/politics-news.xml",),
        description="US politics, Congress, the White House, and campaigns. Feed summaries only: article retrieval is not available.",
        topics=("politics", "policy"),
        geography="United States",
        capabilities=("feed",),
    ),
    Source(
        id="the-hill",
        name="The Hill",
        website="https://thehill.com/",
        feeds=("https://thehill.com/homenews/feed/",),
        aliases=("Hill",),
        description="US congressional, administration, and campaign news with frequent short updates.",
        topics=("politics", "policy"),
        geography="United States",
    ),
    Source(
        id="propublica",
        name="ProPublica",
        website="https://www.propublica.org/",
        feeds=("https://www.propublica.org/feeds/propublica/main",),
        description="Nonprofit investigative journalism on US government, business, justice, and public-interest accountability. Publishes long investigations rather than breaking news.",
        topics=("investigations", "politics", "policy"),
        geography="United States",
    ),
    Source(
        id="scotusblog",
        name="SCOTUSblog",
        website="https://www.scotusblog.com/",
        feeds=("https://www.scotusblog.com/feed/",),
        description="US Supreme Court cases, opinions, arguments, and analysis.",
        topics=("law", "politics"),
        geography="United States",
    ),
    Source(
        id="sec",
        name="SEC",
        website="https://www.sec.gov/",
        feeds=("https://www.sec.gov/news/pressreleases.rss",),
        aliases=("Securities and Exchange Commission",),
        description="Official US Securities and Exchange Commission press releases on enforcement actions, rules, and agency announcements. Primary regulatory statements, not market news.",
        topics=("finance", "regulation"),
        geography="United States",
    ),
    Source(
        id="gao",
        name="GAO",
        website="https://www.gao.gov/",
        feeds=("https://www.gao.gov/rss/reports.xml",),
        aliases=("Government Accountability Office",),
        description="US Government Accountability Office reports and testimony auditing federal programs and spending. Primary oversight documents.",
        topics=("policy", "government", "oversight"),
        geography="United States",
    ),
    Source(
        id="justice-department",
        name="US Department of Justice",
        website="https://www.justice.gov/",
        feeds=("https://www.justice.gov/news/rss?m=1",),
        aliases=("DOJ", "Justice Department"),
        description="Official US Department of Justice press releases on prosecutions, settlements, and enforcement. Primary government statements, not independent reporting.",
        topics=("law", "government"),
        geography="United States",
    ),
    Source(
        id="arxiv",
        name="arXiv",
        website="https://arxiv.org/",
        feeds=("https://rss.arxiv.org/rss/cs.AI+cs.LG+cs.CL",),
        description="New and updated research preprints in artificial intelligence, machine learning, and computational linguistics (arXiv cs.AI, cs.LG, cs.CL), with abstracts. Preprints are not peer reviewed. The feed lists the latest announcement day only and cannot be searched.",
        topics=("research", "ai", "machine-learning"),
        geography="International research",
    ),
)
