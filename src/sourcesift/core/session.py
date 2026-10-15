"""Ephemeral conversations shared by terminal and Python clients."""

from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError

from sourcesift.agents.runtime import (
    ConversationState,
    EventHandler,
    run_agent,
    validate_model_access,
)
from sourcesift.core.config import ContextSettings, Settings
from sourcesift.core.context import prepare_request
from sourcesift.errors import InputError
from sourcesift.models import ContextDocument, Request, Result, SessionEvent
from sourcesift.sources import SourceRegistry


class Session:
    """One bounded in-memory conversation. Failed/cancelled turns never commit.

    Create with ``app.session()``. Settings, sources, and configured context are
    snapshotted. ``reset()`` reloads context files and clears completed turns.
    Only one turn may run at a time; cancel its asyncio task to interrupt it.
    """

    def __init__(
        self,
        settings: Settings,
        registry: SourceRegistry,
        *,
        files: Sequence[str | Path] = (),
    ) -> None:
        self.settings = settings
        self.registry = registry
        self._files = tuple(Path(path).expanduser().resolve() for path in files)
        self._busy = False
        self._state = ConversationState()
        self._turns: list[tuple[str, Result]] = []
        self._context: tuple[ContextDocument, ...] = ()
        self.reset()

    @property
    def busy(self) -> bool:
        """Whether a turn is active (including cleanup after cancellation)."""
        return self._busy

    @property
    def context(self) -> tuple[ContextDocument, ...]:
        """The loaded context snapshot, including explicit personal guidance."""
        return self._context

    @property
    def turns(self) -> tuple[tuple[str, Result], ...]:
        """Completed user prompts and validated results in order."""
        return tuple(self._turns)

    def reset(self) -> None:
        """Start fresh and reload files; a read error preserves the old session."""
        if self.busy:
            raise InputError("Cancel the active turn before starting a new session.")
        context = prepare_request(
            Request(prompt="Initialize session"), self.settings, files=self._files
        ).context
        self._context = context
        self._state = ConversationState()
        self._turns.clear()

    async def run(
        self,
        request: str | Request,
        *,
        files: Sequence[str | Path] = (),
        on_event: EventHandler | None = None,
    ) -> Result:
        """Run a follow-up; optional synchronous callback receives provisional events.

        Callbacks should return quickly without blocking. The returned Result is
        authoritative; drafts can be replaced during citation repair or discarded
        on cancellation/error. Tool/HTTP/model budgets restart for each turn.
        """
        if self.busy:
            raise InputError("A turn is already running in this session.")
        if len(self._turns) >= self.settings.limits.max_session_turns:
            raise InputError("Session turn limit reached; start a new session (/new).")
        self._busy = True
        try:
            try:
                parsed = (
                    Request(prompt=request) if isinstance(request, str) else request
                )
            except ValidationError:
                raise InputError("Provide a nonempty prompt.") from None
            validate_model_access(self.settings)
            # Context is attached once to history, remaining stable until reset.
            parsed = parsed.model_copy(
                update={
                    "context": (self.context if not self._turns else ())
                    + parsed.context
                }
            )
            prepared = prepare_request(
                parsed,
                self.settings.model_copy(update={"context": ContextSettings()}),
                files=files,
            )
            candidate = deepcopy(self._state)
            if on_event:
                on_event(SessionEvent(kind="status", text="Thinking…"))
            result = await run_agent(
                prepared,
                self.settings,
                self.registry,
                state=candidate,
                on_event=on_event,
            )
            self._state = candidate
            self._turns.append((parsed.prompt, result))
            return result
        finally:
            self._busy = False
