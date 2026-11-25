"""Framework-independent request and result contracts."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from sourcesift.contract import Contract
from sourcesift.data import Figure


class ContextDocument(Contract):
    """Text supplied by the user, with a label rather than an external citation."""

    name: str = Field(min_length=1, max_length=512)
    text: str = Field(repr=False)
    role: Literal["background", "document", "guidance"] = "document"


class Step(Contract):
    """One thing the agent did, described for a person: a title, then details."""

    id: str
    tool: str
    state: Literal["running", "done", "failed"]
    title: str
    summary: str = ""
    lines: tuple[str, ...] = ()


class SessionEvent(Contract):
    """UI-independent progress; streamed drafts are provisional until run returns.

    A ``step`` event carries the step as it starts and again when it finishes;
    its ``text`` is the step's title.
    """

    kind: Literal["status", "draft", "reset", "step"]
    text: str = Field(default="", repr=False)
    step: Step | None = None


class Request(Contract):
    """One independent request; documents are context, not system instructions."""

    prompt: str = Field(repr=False)
    context: tuple[ContextDocument, ...] = Field(default=(), repr=False)
    output_format: Literal["markdown", "plain"] = "markdown"

    @field_validator("prompt")
    @classmethod
    def nonempty_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value


class Usage(Contract):
    """Token counts reported by the model runtime; not a billing estimate."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class Reference(Contract):
    """Retrieved evidence behind one citation; URLs and dates come from adapters."""

    id: str
    title: str
    url: str
    requested_url: str
    retrieved_from: str
    publisher: str
    source_id: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None
    retrieved_at: datetime
    kind: Literal["feed_summary", "article", "api_record"]
    limitations: tuple[str, ...] = ()


class Evidence(Reference):
    """Retrieved text retained for a run or session; written only to a saved session."""

    text: str = Field(repr=False)


class Artifact(Contract):
    """A document the agent wrote, or an answer the user kept as one.

    ``markdown`` cites evidence as ``[S1]`` and places figures as
    ``![Title](F1)``. ``notes`` are the application's coverage notes for the turn
    that wrote it. ``id`` (A1, A2, ...) is stable within a conversation and
    ``version`` counts revisions.
    """

    id: str = Field(pattern=r"^A[1-9]\d*$")
    title: str = Field(min_length=1, max_length=120)
    markdown: str = Field(min_length=1, repr=False)
    notes: tuple[str, ...] = ()
    version: int = Field(default=1, ge=1)
    updated_at: datetime


class ResearchWindow(Contract):
    """Inclusive window start and retrieval-time end, with the configured zone."""

    label: Literal["recent", "today", "this_week", "any"]
    timezone: str
    start: datetime | None
    end: datetime


class Result(Contract):
    """Answer, explicit capability limitations, and reported usage.

    ``figures`` are the charts the answer or its artifacts place, in order. Each
    holds its recipe and the retrieved rows; ``sourcesift.render_png`` draws its
    picture. ``artifacts`` are documents written or revised in this turn.
    ``references`` covers the answer, those artifacts, and those figures.
    """

    answer: str = Field(repr=False)
    limitations: tuple[str, ...] = ()
    usage: Usage = Field(default_factory=Usage)
    model: str
    references: tuple[Reference, ...] = ()
    figures: tuple[Figure, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    steps: tuple[Step, ...] = ()
    selected_sources: tuple[str, ...] = ()
    window: ResearchWindow | None = None
    http_requests: int = 0
