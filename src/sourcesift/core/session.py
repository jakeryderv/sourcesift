"""Conversations shared by the web app and Python clients; in memory unless saved."""

from collections.abc import Iterable, Sequence
from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError
from pydantic_ai.messages import ModelMessagesTypeAdapter

from sourcesift.agents.runtime import (
    ConversationState,
    EventHandler,
    run_agent,
    validate_model_access,
)
from sourcesift.core.config import ContextSettings, Settings
from sourcesift.core.context import prepare_request
from sourcesift.core.store import SavedConversation, SavedTurn, SessionStore
from sourcesift.errors import InputError
from sourcesift.extend import Toolkit
from sourcesift.models import (
    ContextDocument,
    Reference,
    Request,
    Result,
    SessionEvent,
)
from sourcesift.retrieval.http import PageCache
from sourcesift.sources import Source, SourceRegistry


class Session:
    """One bounded conversation. Failed/cancelled turns never commit.

    Create with ``app.session()``. Settings, sources, and configured context are
    snapshotted. ``reset()`` reloads context files and clears completed turns.
    Only one turn may run at a time; cancel its asyncio task to interrupt it.

    A conversation stays in memory unless created with ``save=True``; it is then
    written to its own file after each completed turn. ``resume=True`` continues
    the most recently saved conversation and keeps saving to that file.
    """

    def __init__(
        self,
        settings: Settings,
        registry: SourceRegistry,
        *,
        toolkit: Toolkit | None = None,
        files: Sequence[str | Path] = (),
        save: bool = False,
        resume: bool = False,
    ) -> None:
        if resume and files:
            raise InputError(
                "A continued conversation keeps its original context; attach files "
                "in a message instead."
            )
        self.settings = settings
        # The catalog is fixed; ``registry`` is the part enabled for this conversation.
        self._catalog = registry
        self._toolkit = toolkit
        self.registry = registry
        self._store = (
            SessionStore(settings.sessions.directory) if save or resume else None
        )
        self._path: Path | None = None
        # Why the latest completed turn could not be saved, if it could not.
        self.save_error: str | None = None
        self._files = tuple(Path(path).expanduser().resolve() for path in files)
        self._busy = False
        self._state = ConversationState()
        self._turns: list[tuple[str, Result]] = []
        self._context: tuple[ContextDocument, ...] = ()
        self._cache = PageCache(settings.limits.feed_cache_seconds)
        self.reset()
        if resume:
            self._resume()

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

    @property
    def evidence(self) -> tuple[Reference, ...]:
        """Evidence retained for citations so far, in citation-ID order, without text."""
        items = sorted(self._state.evidence.values(), key=lambda item: int(item.id[1:]))
        return tuple(
            Reference.model_validate(item.model_dump(exclude={"text"}))
            for item in items
        )

    @property
    def saved_path(self) -> Path | None:
        """The file this conversation is saved to, once a turn has been saved."""
        return self._path if self._path and self._turns else None

    def _resume(self) -> None:
        assert self._store is not None
        path = self._store.latest()
        if path is None:
            raise InputError("There is no saved conversation to continue.")
        # Generous bound: the state budget plus results and context snapshots.
        saved = self._store.read(path, 8 * self.settings.limits.max_session_bytes)
        try:
            messages = ModelMessagesTypeAdapter.validate_python(saved.messages)
        except ValidationError:
            raise InputError(
                "The saved conversation cannot be read; start a new one."
            ) from None
        state = ConversationState(
            messages,
            {item.url: item for item in saved.evidence},
            saved.next_id,
            saved.limitations,
        )
        if state.size_bytes() > self.settings.limits.max_session_bytes:
            raise InputError(
                "The saved conversation exceeds limits.max_session_bytes; start a new one."
            )
        self._state = state
        self._turns = [(turn.prompt, turn.result) for turn in saved.turns]
        self._context = saved.context
        self._path = path

    def _save(self) -> None:
        if self._store is None:
            return
        path = self._path or self._store.new_path()
        self._store.write(
            path,
            SavedConversation(
                model=self.settings.agent.model,
                messages=ModelMessagesTypeAdapter.dump_python(
                    self._state.messages, mode="json"
                ),
                evidence=tuple(self._state.evidence.values()),
                next_id=self._state.next_id,
                limitations=self._state.limitations,
                turns=tuple(
                    SavedTurn(prompt=prompt, result=result)
                    for prompt, result in self._turns
                ),
                context=self._context,
            ),
        )
        self._path = path

    @property
    def sources(self) -> tuple[tuple[Source, bool], ...]:
        """Every catalog source with whether this conversation may use it."""
        enabled = {source.id for source in self.registry.list()}
        return tuple((source, source.id in enabled) for source in self._catalog.list())

    def enable_sources(self, source_ids: Iterable[str]) -> None:
        """Limit later turns to these catalog sources; ``reset()`` restores all.

        Evidence already retrieved stays citable. An empty selection leaves only
        supplied documents and URLs given in a prompt.
        """
        if self.busy:
            raise InputError(
                "Finish or cancel the active turn before changing sources."
            )
        wanted = set(source_ids)
        if wanted - {source.id for source in self._catalog.list()}:
            raise InputError("Enabled source IDs must exist in the catalog.")
        self.registry = SourceRegistry(
            source for source in self._catalog.list() if source.id in wanted
        )

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
        self._cache.clear()
        self.registry = self._catalog
        # A fresh conversation gets its own file; the previous one is kept.
        self._path = None

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
            raise InputError("Session turn limit reached; start a new conversation.")
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
                cache=self._cache,
                toolkit=self._toolkit,
            )
            self._state = candidate
            self._turns.append((parsed.prompt, result))
            # A turn that cannot be saved is still complete and returned.
            try:
                self._save()
                self.save_error = None
            except InputError as exc:
                self.save_error = str(exc)
            return result
        finally:
            self._busy = False
