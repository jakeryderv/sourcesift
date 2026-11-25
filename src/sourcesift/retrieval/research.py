"""Per-run retrieval state: source constraints, evidence, freshness, and budgets."""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from sourcesift.artifacts import (
    CITATION,
    FIGURE,
    MAX_ARTIFACTS,
    artifact_problem,
    citations_in,
)
from sourcesift.builtin import builtin_toolkit
from sourcesift.core.config import Settings
from sourcesift.data import Figure, FigureKind, Table
from sourcesift.extend import FetchContext, Toolkit
from sourcesift.figures import check_figure
from sourcesift.models import Artifact, Evidence, Reference, ResearchWindow
from sourcesift.retrieval.http import Fetcher, Page, PageCache
from sourcesift.retrieval.parsing import (
    ParsedItem,
    discover_feeds,
    parse_article,
    parse_feed,
)
from sourcesift.retrieval.urls import RetrievalError, hostname, normalize_url
from sourcesift.sources import Source, SourceRegistry

WindowName = Literal["recent", "today", "this_week", "any"]
MAX_CONVERSATION_FIGURES = 48


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


@dataclass(frozen=True)
class Dataset:
    """Tables one data source query returned, tied to the evidence it produced."""

    source_id: str
    tables: tuple[Table, ...]
    evidence_ids: tuple[str, ...]


def _problems(exc: ValidationError) -> str:
    """Field names and messages only; never the rejected input."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'value'}: {error['msg']}"
        for error in exc.errors(include_input=False, include_url=False)[:5]
    )


def _trim_url(value: str) -> str:
    """Drop sentence punctuation after a link, keeping a bracket the link opened."""
    pairs = {")": "(", "]": "[", "}": "{"}
    while value and value[-1] in ".,;:!?)]}":
        last = value[-1]
        if last in pairs and value.count(pairs[last]) >= value.count(last):
            break
        value = value[:-1]
    return value


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
        cache: PageCache | None = None,
        toolkit: Toolkit | None = None,
        datasets: dict[str, Dataset] | None = None,
        figures: dict[str, Figure] | None = None,
        artifacts: dict[str, Artifact] | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.toolkit = toolkit if toolkit is not None else builtin_toolkit()
        # Evidence ID -> the data returned with it, including earlier turns'.
        self.datasets = dict(datasets or {})
        # Figure ID -> figure, including earlier turns'; ``made`` is this run's.
        self.figures = dict(figures or {})
        self.made: list[str] = []
        # Artifact ID -> artifact, including earlier turns'; ``written`` is this run's.
        self.artifacts = dict(artifacts or {})
        self.written: list[str] = []
        self.fetcher = fetcher
        self.cache = cache
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
                self.direct.add(normalize_url(_trim_url(value)))
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
        reply: dict[str, object] = {
            "window": self.window.model_dump(mode="json") if self.window else None,
            "evidence": [
                item.model_dump(mode="json") for item in self.evidence.values()
            ],
            "limitations": self.limitations,
        }
        tables = [
            {
                "evidence_id": data.evidence_ids[0],
                "tables": [table.describe() for table in data.tables],
            }
            for data in {id(d): d for d in self.datasets.values()}.values()
        ]
        if tables:
            reply["chartable"] = tables
        return reply

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

    async def query_source(
        self,
        source_id: str,
        params: dict[str, Any] | None = None,
        window: WindowName = "recent",
    ) -> dict[str, object]:
        """Query one catalog source whose capabilities include "query".

        These sources return live data instead of a feed. Pass params as an object
        matching the source's params schema in the catalog. Use window as for
        research; a window or named-publication constraint already set in this
        request stays in force. Returned records are evidence to cite like any
        other, and "chartable" lists the tables make_figure can draw.
        """
        self.attempted = True
        if self.window is None:
            self.window = make_window(window, self.settings, self.now)
            self.only = ()
        source = self.registry.resolve(source_id)
        data_source = self.toolkit.sources.get(source.id) if source else None
        if source is None or data_source is None:
            self.note("A queried source is unknown, disabled, or not queryable.")
            return self._reply()
        only = [self.registry.resolve(name) for name in self.only or ()]
        if self.only and source.id not in {s.id for s in only if s is not None}:
            self.note("A source outside the requested publications was skipped.")
            return self._reply()
        try:
            parsed = data_source.params.model_validate(params or {})
        except ValidationError as exc:
            # Returned to the model to correct, not recorded as a coverage gap.
            return self._reply() | {
                "error": f"Invalid params for {source.id}: {_problems(exc)}"
            }
        if source.id not in self.selected:
            if len(self.selected) >= self.settings.limits.max_sources:
                self.note("Source limit reached; coverage is partial.")
                return self._reply()
            self.selected.append(source.id)
        limit = self.settings.limits.max_items_per_source
        try:
            result = await data_source.fetch(
                parsed,
                FetchContext(
                    data_source.bounded(self.fetcher.get),
                    self.now,
                    self.window.start,
                    limit,
                ),
            )
            if not result.evidence:
                self.note(f"{source.name}: the query returned no records.")
            ids = []
            for record in list(result.evidence)[:limit]:
                item = ParsedItem(
                    record.title,
                    record.url,
                    record.text,
                    record.author,
                    record.published_at,
                )
                if self._add(item, record.page, source.id, "api_record"):
                    ids.append(self.evidence[item.url].id)
            tables = tuple(t for t in result.tables if isinstance(t, Table))
            if ids and tables:
                dataset = Dataset(source.id, tables, tuple(ids))
                self.datasets.update(dict.fromkeys(ids, dataset))
        except RetrievalError as exc:
            self.note(f"{source.name}: {exc}")
        return self._reply()

    async def make_figure(
        self,
        evidence_id: str,
        kind: FigureKind,
        x: str,
        y: list[str],
        table: str = "",
        series: str = "",
        title: str = "",
        log_scale: bool = False,
    ) -> dict[str, object]:
        """Draw a chart from a table returned by query_source.

        Pass an evidence_id listed under "chartable" and name columns exactly as
        listed there. kind is line or area (numbers over a time or number
        column), bar or stacked_bar (numbers across categories), scatter (how two
        numbers relate), or donut (parts of a whole, a dozen rows at most). x is
        the horizontal axis column (for donut, the column naming each part); y
        lists one to eight numeric columns, one series each. series optionally
        names a text column that splits a single y column into one series per
        value. When the evidence has several tables, pass the table's name. The
        application draws the chart from the retrieved rows: values cannot be
        passed in. The reply gives the figure's ID and the Markdown that places it.
        """
        key = evidence_id.strip().strip("[]")
        dataset = self.datasets.get(key)
        if dataset is None:
            return {
                "error": "No table is attached to that evidence. Only evidence listed "
                "under chartable, from query_source in this conversation, can be drawn."
            }
        wanted = " ".join(table.split()).casefold()
        candidates = [
            t for t in dataset.tables if not wanted or t.name.casefold() == wanted
        ]
        if not candidates:
            names = "; ".join(t.name for t in dataset.tables)
            return {"error": f"No table has that name. Tables: {names}."}
        number = 1 + max((int(name[1:]) for name in self.figures), default=0)
        # Without a table name, the first table the columns fit is drawn.
        figure = None
        problem = "That chart could not be drawn from this data."
        for candidate in candidates:
            try:
                figure = Figure(
                    id=f"F{number}",
                    title=" ".join(title.split())[:120] or candidate.name,
                    kind=kind,
                    x=x,
                    y=tuple(y),
                    series=series,
                    log_scale=log_scale,
                    source_id=dataset.source_id,
                    evidence_ids=dataset.evidence_ids,
                    table=candidate,
                )
                check_figure(figure)
            except ValidationError as exc:
                figure, problem = None, f"Invalid chart: {_problems(exc)}"
            except ValueError as exc:
                figure, problem = None, " ".join(str(exc).split())[:300] or problem
            else:
                break
        if figure is None:
            return {"error": problem}
        recipe = figure.model_dump(exclude={"id"})
        for existing in self.figures.values():
            if existing.model_dump(exclude={"id"}) == recipe:
                return self._placed(existing)
        if len(self.made) >= self.settings.limits.max_figures:
            return {"error": "The limit on figures for one answer was reached."}
        if len(self.figures) >= MAX_CONVERSATION_FIGURES:
            return {"error": "This conversation has reached its limit on figures."}
        self.figures[figure.id] = figure
        self.made.append(figure.id)
        return self._placed(figure)

    @staticmethod
    def _placed(figure: Figure) -> dict[str, object]:
        return {
            "figure": figure.id,
            "title": figure.title,
            "place": f"![{figure.title}]({figure.id})",
            "cite": f"[{figure.evidence_ids[0]}]",
        }

    async def write_artifact(
        self, title: str, markdown: str, artifact_id: str = ""
    ) -> dict[str, object]:
        """Write or revise an artifact: a document the user keeps and can export.

        markdown is the whole document: headings and prose in plain Markdown,
        [S1] citations for every external claim, and figures placed on their own
        line as ![Title](F1). Do not write a title heading, a YAML header, a
        reference list, code that runs, HTML, or images other than figures; the
        application adds the title, date, and references. To revise, pass the
        artifact_id of an existing artifact and the full new text.
        """
        key = artifact_id.strip().strip("[]")
        existing = self.artifacts.get(key) if key else None
        if key and existing is None:
            known = ", ".join(self.artifacts) or "none"
            return {"error": f"There is no artifact {key}. Artifacts: {known}."}
        problem = artifact_problem(
            title,
            markdown,
            evidence_ids=(item.id for item in self.all_evidence.values()),
            figure_ids=self.figures,
            max_chars=self.settings.limits.max_artifact_chars,
        )
        if problem:
            return {"error": problem}
        if existing is None and len(self.artifacts) >= MAX_ARTIFACTS:
            return {"error": "This conversation has reached its limit on artifacts."}
        number = 1 + max((int(name[1:]) for name in self.artifacts), default=0)
        artifact = Artifact(
            id=existing.id if existing else f"A{number}",
            title=" ".join(title.split())[:120],
            markdown=markdown.strip(),
            version=existing.version + 1 if existing else 1,
            updated_at=self.now,
        )
        self.artifacts[artifact.id] = artifact
        if artifact.id not in self.written:
            self.written.append(artifact.id)
        return {
            "artifact": artifact.id,
            "title": artifact.title,
            "version": artifact.version,
        }

    def written_text(self) -> str:
        """The text of every artifact written or revised in this run."""
        return "\n".join(self.artifacts[key].markdown for key in self.written)

    def cited(self, answer: str) -> set[str]:
        """Evidence the answer or this run's artifacts cite, in text or by a figure."""
        text = answer + "\n" + self.written_text()
        return citations_in(text) | {
            figure.evidence_ids[0] for figure in self.figures_in(text)
        }

    def figures_in(self, text: str) -> tuple[Figure, ...]:
        """Known figures the text places, in first-use order."""
        ids = dict.fromkeys(FIGURE.findall(text))
        return tuple(self.figures[key] for key in ids if key in self.figures)

    def unknown_figures(self, text: str) -> set[str]:
        return set(FIGURE.findall(text)) - set(self.figures)

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

    async def _feed_page(self, url: str) -> Page:
        """Fetch a feed or its discovery page, reusing this conversation's recent copy.

        A cached page costs no request; it passed the robots check when fetched.
        Articles are never cached, so reading one always retrieves it again.
        """
        key = normalize_url(url)
        cached = self.cache.get(key) if self.cache is not None else None
        if cached is not None:
            return cached
        page = await self.fetcher.get(url)
        if self.cache is not None:
            self.cache.set(key, page)
        return page

    async def _source(self, source: Source) -> None:
        if "query" in source.capabilities:
            raise RetrievalError("This source is queried with query_source.")
        if "feed" not in source.capabilities:
            raise RetrievalError("This source does not offer feed access.")
        feeds = source.feeds
        if not feeds:
            feeds = discover_feeds(await self._feed_page(source.website))
            if not feeds:
                raise RetrievalError("No RSS/Atom feed was declared by the website.")
        count = 0
        for url in feeds:
            try:
                page = await self._feed_page(url)
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
        kind: Literal["feed_summary", "article", "api_record"],
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
        if date is None and kind == "api_record":
            # A data record states its own reporting period in its text.
            pass
        elif date is None:
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
            retrieved_at=page.fetched_at,
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
        """Return cited references in first-citation order, never fabricated URLs.

        A placed figure counts as citing the evidence its table came with.
        """
        by_id = {item.id: item for item in self.all_evidence.values()}
        ids = dict.fromkeys("S" + value for value in CITATION.findall(answer))
        for figure in self.figures_in(answer):
            ids.setdefault(figure.evidence_ids[0])
        return tuple(
            Reference.model_validate(by_id[key].model_dump(exclude={"text"}))
            for key in ids
            if key in by_id
        )
