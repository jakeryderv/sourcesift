"""Per-run retrieval state: source constraints, evidence, freshness, and budgets."""

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sourcesift.core.config import Settings
from sourcesift.models import Evidence, Reference, ResearchWindow
from sourcesift.retrieval.http import Fetcher, Page
from sourcesift.retrieval.parsing import (
    ParsedItem,
    discover_feeds,
    parse_article,
    parse_feed,
)
from sourcesift.retrieval.urls import RetrievalError, hostname, normalize_url
from sourcesift.sources import Source, SourceRegistry

WindowName = Literal["recent", "today", "this_week", "any"]
CITATION = re.compile(r"\[S(\d+)\]")


def make_window(label: WindowName, settings: Settings, now: datetime) -> ResearchWindow:
    """Today/week use local midnight (Monday for week); recent is a rolling window."""
    local = now.astimezone(ZoneInfo(settings.sources.timezone))
    start = None
    if label == "recent":
        start = now - timedelta(days=settings.sources.recent_days)
    elif label in {"today", "this_week"}:
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if label == "this_week":
            start -= timedelta(days=local.weekday())
    return ResearchWindow(
        label=label, timezone=settings.sources.timezone, start=start, end=now
    )


class Research:
    """Bounded shared tool implementation, independent of the model framework."""

    def __init__(
        self,
        settings: Settings,
        registry: SourceRegistry,
        fetcher: Fetcher,
        prompt: str,
        *,
        now: datetime | None = None,
        previous: dict[str, Evidence] | None = None,
        next_id: int = 1,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.fetcher = fetcher
        self.now = now or datetime.now(UTC)
        self.window: ResearchWindow | None = None
        self.selected: list[str] = []
        self._notes: list[str] = []
        self.evidence: dict[str, Evidence] = {}
        self.previous = dict(previous or {})
        self.allowed: set[str] = set()
        self.direct: set[str] = set()
        for value in re.findall(r"https?://[^\s<>\"']+", prompt):
            try:
                self.direct.add(normalize_url(value.rstrip(".,;:!?)]}")))
            except RetrievalError:
                pass
        self.allowed.update(self.direct)
        self.allowed.update(self.previous)
        self.only: tuple[str, ...] | None = None
        self.attempted = False
        self.articles = 0
        self._read: set[str] = set()
        self._next_id = next_id
        self._fingerprints: dict[str, bytes] = {}

    @property
    def all_evidence(self) -> dict[str, Evidence]:
        """Current evidence supersedes earlier snapshots with the same identity."""
        return self.previous | self.evidence

    @property
    def next_id(self) -> int:
        """Next unused citation number, including IDs removed by date validation."""
        return self._next_id

    def note(self, text: str) -> None:
        if text not in self._notes:
            self._notes.append(text)

    def limitations_for(self, references: tuple[Reference, ...]) -> list[str]:
        """Combine run-wide gaps with limitations of the evidence actually cited."""
        notes = list(self._notes)
        if self.attempted and not self.evidence:
            notes.append(
                "No usable evidence was retrieved for this window; current reporting could not be verified."
            )
        notes.extend(warning for ref in references for warning in ref.limitations)
        return list(dict.fromkeys(notes))

    @property
    def limitations(self) -> list[str]:
        """Current coverage and evidence limitations, refreshed after upgrades."""
        return self.limitations_for(tuple(self.evidence.values()))

    def _reply(self) -> dict[str, object]:
        return {
            "window": self.window.model_dump(mode="json") if self.window else None,
            "evidence": [
                item.model_dump(mode="json") for item in self.evidence.values()
            ],
            "limitations": self.limitations,
        }

    async def research(
        self,
        source_ids: list[str],
        direct_urls: list[str],
        only_sources: list[str],
        window: WindowName = "recent",
    ) -> dict[str, object]:
        """Read selected feeds or user-supplied URLs; call before read_article.

        Select IDs semantically from the catalog. For a request limited to named
        publications, pass their exact names in only_sources (even if unknown).
        An unknown/disabled publication never falls back to another source.
        Pass direct_urls only for links present in the task. window is recent
        (configured rolling days), today, this_week (Monday), or any for an article
        summary with no freshness requirement. Constraints cannot change mid-run.
        Feed summaries are evidence, not proof that a full article was fetched.
        """
        self.attempted = True
        if self.window is None:
            self.window = make_window(window, self.settings, self.now)
            self.only = tuple(only_sources)
        elif window != self.window.label or tuple(only_sources) != self.only:
            self.note(
                "Source constraints and time window cannot change during a request."
            )
            return self._reply()
        resolved_only = [self.registry.resolve(name) for name in self.only or ()]
        if any(source is None for source in resolved_only):
            self.note(
                "A requested publication is unknown or disabled; no substitute sources were retrieved."
            )
            return self._reply()
        allowed_ids = {source.id for source in resolved_only if source is not None}
        for name in source_ids:
            source = self.registry.resolve(name)
            if source is None:
                self.note("A selected source is unknown or disabled.")
                continue
            if self.only and source.id not in allowed_ids:
                self.note("A source outside the requested publications was skipped.")
                continue
            if source.id in self.selected:
                continue
            if len(self.selected) >= self.settings.limits.max_sources:
                self.note("Source limit reached; coverage is partial.")
                break
            self.selected.append(source.id)
            try:
                await self._source(source)
            except RetrievalError as exc:
                self.note(f"{source.name}: {exc}")
        for url in direct_urls[: self.settings.limits.max_articles]:
            try:
                normalized = normalize_url(url)
                if normalized not in self.direct:
                    raise RetrievalError("Direct URL was not present in the task.")
                # Named-only is a semantic evidence constraint, not a domain sandbox.
                if self.only:
                    raise RetrievalError(
                        "Use the named publication's registered feed for a named-only request."
                    )
                await self._article(normalized)
            except RetrievalError as exc:
                self.note(str(exc))
        if len(direct_urls) > self.settings.limits.max_articles:
            self.note("Article limit reached; coverage is partial.")
        return self._reply()

    async def read_article(self, url: str) -> dict[str, object]:
        """Read a returned article link for detail, within the original constraints.

        Only user-provided URLs or links in retrieved evidence are eligible.
        Links may redirect or cite other publishers: use the actual publisher and
        provenance, and never attribute linked reporting to the original source.
        """
        self.attempted = True
        try:
            if self.window is None:
                if normalize_url(url) not in self.previous:
                    raise RetrievalError(
                        "Call research first to establish a window and source constraints."
                    )
                self.window = make_window("any", self.settings, self.now)
                self.only = ()
            normalized = normalize_url(url)
            if normalized not in self.allowed or (
                self.only and normalized not in self.evidence
            ):
                raise RetrievalError(
                    "Article URL is outside the retrieved evidence or original task."
                )
            await self._article(normalized)
        except RetrievalError as exc:
            self.note(str(exc))
        return self._reply()

    async def _source(self, source: Source) -> None:
        if "feed" not in source.capabilities:
            raise RetrievalError("This source does not offer feed access.")
        feeds = source.feeds
        if not feeds:
            feeds = discover_feeds(await self.fetcher.get(source.website))
            if not feeds:
                raise RetrievalError("No RSS/Atom feed was declared by the website.")
        count = 0
        for url in feeds:
            try:
                page = await self.fetcher.get(url)
                items, malformed = parse_feed(page)
                if malformed:
                    self.note(
                        f"{source.name}: feed is malformed; only usable entries were considered."
                    )
                if not items:
                    self.note(f"{source.name}: feed contained no usable entries.")
                # Prefer recent dated items, retaining unknown dates with a warning.
                items.sort(
                    key=lambda item: (
                        item.published_at
                        or item.updated_at
                        or datetime.min.replace(tzinfo=UTC)
                    ),
                    reverse=True,
                )
                for item in items:
                    if self._add(item, page, source.id, "feed_summary"):
                        count += 1
                    if count >= self.settings.limits.max_items_per_source:
                        self.note(
                            f"{source.name}: feed selection is capped at {count} items; coverage is partial."
                        )
                        return
            except RetrievalError as exc:
                self.note(f"{source.name}: {exc}")

    async def _article(self, url: str) -> None:
        if url in self._read:
            return
        if self.articles >= self.settings.limits.max_articles:
            raise RetrievalError("Article limit reached.")
        previous = self.all_evidence.get(url)
        source = (
            self.registry.resolve(previous.source_id)
            if previous and previous.source_id
            else None
        )
        if source and "article" not in source.capabilities:
            raise RetrievalError("This source does not offer article access.")
        self.articles += 1
        self._read.add(url)
        page = await self.fetcher.get(url)
        item = parse_article(page, self.settings.limits.max_item_chars)
        previous = self.all_evidence.get(url)
        if previous:
            # Explicit article dates take precedence; feed dates fill missing fields.
            item = ParsedItem(
                item.title,
                item.url,
                item.text,
                item.author or previous.author,
                item.published_at or previous.published_at,
                item.updated_at or previous.updated_at,
            )
        source_id = previous.source_id if previous else None
        if hostname(page.url).removeprefix("www.") != hostname(url).removeprefix(
            "www."
        ):
            source_id = None
            self.note(
                "An article redirected to a different publisher; see its final URL and publisher."
            )
        self._add(item, page, source_id, "article", replacing=url if previous else None)

    def _add(
        self,
        item: ParsedItem,
        page: Page,
        source_id: str | None,
        kind: Literal["feed_summary", "article"],
        *,
        replacing: str | None = None,
    ) -> bool:
        assert self.window is not None
        date = item.published_at or item.updated_at
        if date is not None and (
            date > self.window.end
            or (self.window.start is not None and date < self.window.start)
        ):
            self.note(
                "Entries outside the requested date window were excluded; feeds do not provide archive search."
            )
            if replacing:
                self.evidence.pop(replacing, None)
                self.previous.pop(replacing, None)
                self._fingerprints.pop(replacing, None)
            return False
        existing = self.all_evidence.get(item.url) or self.all_evidence.get(
            replacing or item.url
        )
        if item.url in self.evidence and kind == "feed_summary":
            return False
        digest = hashlib.sha256(
            " ".join((item.title + " " + item.text).casefold().split()).encode()
        ).digest()
        if any(
            value == digest
            for url, value in self._fingerprints.items()
            if url not in {item.url, replacing}
        ):
            return False
        if replacing and replacing != item.url:
            self.evidence.pop(replacing, None)
            self.previous.pop(replacing, None)
            self._fingerprints.pop(replacing, None)
        limits = self.settings.limits
        if item.url not in self.evidence and len(self.evidence) >= limits.max_items:
            self.note("Evidence item limit reached; coverage is partial.")
            return False
        remaining = limits.max_evidence_chars - sum(
            len(e.text) for e in self.evidence.values() if e is not existing
        )
        if remaining <= 0:
            self.note("Evidence text limit reached; coverage is partial.")
            return False
        text = item.text[: min(limits.max_item_chars, remaining)]
        warnings = []
        if date is None:
            warnings.append(
                "Publication/update date is unknown; freshness is unverified."
            )
        elif item.published_at is None:
            warnings.append(
                "Only an update date is available; original publication date is unknown."
            )
        if len(text) < len(item.text):
            warnings.append("Evidence text was truncated to the configured limit.")
        if kind == "feed_summary":
            warnings.append(
                "Only the feed summary was retrieved, not the full article."
            )
        reference = Evidence(
            id=existing.id if existing else f"S{self._next_id}",
            title=item.title,
            url=item.url,
            requested_url=page.requested_url,
            retrieved_from=page.url,
            publisher=hostname(item.url),
            source_id=source_id,
            author=item.author,
            published_at=item.published_at,
            updated_at=item.updated_at,
            retrieved_at=datetime.now(UTC),
            kind=kind,
            limitations=tuple(warnings),
            text=text,
        )
        if replacing:
            self.evidence.pop(replacing, None)
        if existing is None:
            self._next_id += 1
        self._fingerprints[item.url] = digest
        self.evidence[item.url] = reference
        self.allowed.add(item.url)
        return True

    def references(self, answer: str) -> tuple[Reference, ...]:
        """Return cited references in first-citation order, never fabricated URLs."""
        by_id = {item.id: item for item in self.all_evidence.values()}
        ids = dict.fromkeys("S" + value for value in CITATION.findall(answer))
        return tuple(
            Reference.model_validate(by_id[key].model_dump(exclude={"text"}))
            for key in ids
            if key in by_id
        )
