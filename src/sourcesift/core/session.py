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
from sourcesift.artifacts import (
    MAX_ARTIFACTS,
    artifact_from_answer,
    new_artifact_folder,
    save_artifacts,
    title_from,
)
from sourcesift.core.config import ContextSettings, Settings
from sourcesift.core.context import prepare_request
from sourcesift.core.store import SavedConversation, SavedTurn, SessionStore
from sourcesift.data import Figure
from sourcesift.errors import InputError
from sourcesift.extend import Toolkit
from sourcesift.models import (
    Artifact,
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
    written to its own folder after each completed turn, along with its
    artifacts as files. ``resume=True`` continues the most recently saved
    conversation, ``resume="<id>"`` a particular one, and both keep saving to it.
    """

    def __init__(
        self,
        settings: Settings,
        registry: SourceRegistry,
        *,
        toolkit: Toolkit | None = None,
        files: Sequence[str | Path] = (),
        save: bool = False,
        resume: bool | str = False,
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
        self._id: str | None = None
        self._saved = False
        self._title = ""
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
            self._resume(None if resume is True else resume)

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
    def figures(self) -> tuple[Figure, ...]:
        """Every figure made in this conversation, in ID order."""
        return tuple(self._state.figures.values())

    @property
    def artifacts(self) -> tuple[Artifact, ...]:
        """The current version of every artifact in this conversation."""
        return tuple(self._state.artifacts.values())

    def artifact_versions(self, artifact_id: str) -> tuple[Artifact, ...]:
        """Every version of an artifact that this conversation still holds, oldest first.

        Each turn's result keeps the artifact as that turn wrote it, so a
        revision does not lose the text it replaced. An answer kept as an
        artifact and revised later has no stored first version: it is that
        turn's answer.
        """
        found = {
            item.version: item
            for _, result in self._turns
            for item in result.artifacts
            if item.id == artifact_id
        }
        current = self._state.artifacts.get(artifact_id)
        if current is None:
            raise InputError("There is no such artifact.")
        found[current.version] = current
        return tuple(found[version] for version in sorted(found))

    def keep_answer(self, turn: int = -1) -> Artifact:
        """Turn a completed answer into an artifact and return it.

        ``turn`` indexes ``turns``; the default is the latest. The artifact keeps
        the answer's citations and figures and can be revised in later turns.
        """
        if self.busy:
            raise InputError("Finish or cancel the active turn first.")
        try:
            prompt, result = self._turns[turn]
        except IndexError:
            raise InputError("There is no such answer to keep.") from None
        if len(self._state.artifacts) >= MAX_ARTIFACTS:
            raise InputError("This conversation has reached its limit on artifacts.")
        number = 1 + max((int(key[1:]) for key in self._state.artifacts), default=0)
        artifact = artifact_from_answer(prompt, result, artifact_id=f"A{number}")
        self._state.artifacts[artifact.id] = artifact
        try:
            self._save()
            self.save_error = None
        except InputError as exc:
            self.save_error = str(exc)
        return artifact

    def save_artifacts(self, directory: str | Path | None = None) -> list[Path]:
        """Write every artifact, with its references and figures, into a folder.

        ``directory`` defaults to a saved conversation's own ``artifacts_path``,
        or to a new folder in the artifacts directory for one kept in memory.
        See ``sourcesift.save_artifacts`` for the files written.
        """
        if not self._state.artifacts:
            raise InputError("There is no artifact to save yet.")
        folder = (
            Path(directory)
            if directory is not None
            else self.artifacts_path
            or new_artifact_folder(
                self.settings.artifacts.directory, self.artifacts[0].title
            )
        )
        return save_artifacts(folder, self.artifacts, self.evidence, self.figures)

    @property
    def id(self) -> str | None:
        """The saved conversation's ID; ``None`` for one kept in memory."""
        return self._id

    @property
    def title(self) -> str:
        """A short name: the first request, unless ``rename`` set another."""
        return self._title or (title_from(self._turns[0][0]) if self._turns else "")

    def rename(self, title: str) -> None:
        """Give the conversation a name; a saved one is rewritten with it."""
        cleaned = " ".join(title.split())[:120]
        if not cleaned:
            raise InputError("Give the conversation a name.")
        if self.busy:
            raise InputError("Finish or cancel the active turn before renaming.")
        self._title = cleaned
        if self._saved:
            self._save(touch=False)

    @property
    def saved_path(self) -> Path | None:
        """The file this conversation is saved to, once a turn has been saved."""
        if self._store is None or self._id is None or not self._saved:
            return None
        return self._store.path(self._id)

    @property
    def artifacts_path(self) -> Path | None:
        """The folder a saved conversation's artifacts are written to."""
        path = self.saved_path
        return path.parent / "artifacts" if path else None

    def _resume(self, conversation_id: str | None) -> None:
        assert self._store is not None
        conversation_id = conversation_id or self._store.latest()
        if conversation_id is None:
            raise InputError("There is no saved conversation to continue.")
        # Generous bound: the state budget plus results and context snapshots.
        saved = self._store.read(
            conversation_id, 8 * self.settings.limits.max_session_bytes
        )
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
            figures={item.id: item for item in saved.figures},
            artifacts={item.id: item for item in saved.artifacts},
        )
        if state.size_bytes() > self.settings.limits.max_session_bytes:
            raise InputError(
                "The saved conversation exceeds limits.max_session_bytes; start a new one."
            )
        self._state = state
        self._turns = [(turn.prompt, turn.result) for turn in saved.turns]
        self._context = saved.context
        self._title = saved.title
        self._id = conversation_id
        self._saved = True

    def _save(self, *, touch: bool = True) -> None:
        if self._store is None:
            return
        assert self._id is not None
        self._store.write(
            self._id,
            SavedConversation(
                title=self.title,
                model=self.settings.agent.model,
                messages=ModelMessagesTypeAdapter.dump_python(
                    self._state.messages, mode="json"
                ),
                evidence=tuple(self._state.evidence.values()),
                figures=tuple(self._state.figures.values()),
                artifacts=tuple(self._state.artifacts.values()),
                next_id=self._state.next_id,
                limitations=self._state.limitations,
                turns=tuple(
                    SavedTurn(prompt=prompt, result=result)
                    for prompt, result in self._turns
                ),
                context=self._context,
            ),
            touch=touch,
        )
        self._saved = True
        if self._state.artifacts:
            # The same documents as files, kept current beside the conversation.
            save_artifacts(
                self._store.folder(self._id) / "artifacts",
                self.artifacts,
                self.evidence,
                self.figures,
            )

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
        # A fresh conversation gets its own folder; the previous one is kept.
        self._id = self._store.new_id() if self._store else None
        self._saved = False
        self._title = ""

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
