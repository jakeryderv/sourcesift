"""Framework-independent request and result contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    """Immutable, validated public data."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class ContextDocument(Contract):
    """Text supplied by the user, with a label rather than an external citation."""

    name: str = Field(min_length=1, max_length=512)
    text: str = Field(repr=False)
    role: Literal["background", "document"] = "document"


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
    kind: Literal["feed_summary", "article"]
    limitations: tuple[str, ...] = ()


class Evidence(Reference):
    """Per-run text supplied to the model, never persisted by SourceSift."""

    text: str = Field(repr=False)


class ResearchWindow(Contract):
    """Inclusive window start and retrieval-time end, with the configured zone."""

    label: Literal["recent", "today", "this_week", "any"]
    timezone: str
    start: datetime | None
    end: datetime


class Result(Contract):
    """Answer, explicit capability limitations, and reported usage."""

    answer: str = Field(repr=False)
    limitations: tuple[str, ...] = ()
    usage: Usage = Field(default_factory=Usage)
    model: str
    references: tuple[Reference, ...] = ()
    selected_sources: tuple[str, ...] = ()
    window: ResearchWindow | None = None
    http_requests: int = 0
