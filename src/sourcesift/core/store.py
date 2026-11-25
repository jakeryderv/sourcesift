"""Saved conversations. Nothing is written unless saving is requested.

Each conversation has its own folder, named by its ID::

    <sessions directory>/<ID>/conversation.json   the conversation itself
    <sessions directory>/<ID>/meta.json           its title and size, for listing
    <sessions directory>/<ID>/artifacts/          its artifacts, as saved files

A saved conversation holds prompts, answers, retrieved evidence text, and the
text of any attached documents, so the folders are private to the user.
Credentials and settings are never saved.
"""

import json
import os
import re
import secrets
import shutil
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from platformdirs import user_data_path
from pydantic import ValidationError

from sourcesift.data import Figure
from sourcesift.errors import InputError
from sourcesift.models import Artifact, ContextDocument, Contract, Evidence, Result

_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{8}")
MAX_META_BYTES = 16_384


class SavedTurn(Contract):
    """One completed prompt and its validated result."""

    prompt: str
    result: Result


class SavedConversation(Contract):
    """The file format; a different ``version`` is rejected rather than guessed at."""

    version: Literal[2] = 2
    title: str = ""
    model: str | None = None
    # Model framework messages, validated by the session when it resumes.
    messages: list[Any]
    evidence: tuple[Evidence, ...]
    figures: tuple[Figure, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    next_id: int
    limitations: tuple[str, ...]
    turns: tuple[SavedTurn, ...]
    context: tuple[ContextDocument, ...]


class ConversationInfo(Contract):
    """What a list of saved conversations shows about one of them."""

    id: str
    title: str
    updated_at: datetime
    turns: int
    artifacts: int = 0


def default_sessions_path() -> Path:
    """Return the platform's per-user SourceSift conversations directory."""
    return user_data_path("sourcesift", appauthor=False) / "sessions"


class SessionStore:
    """One private folder per conversation."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(
            directory if directory is not None else default_sessions_path()
        ).expanduser()

    def new_id(self) -> str:
        """Name a conversation by its UTC start time plus a random suffix."""
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{secrets.token_hex(4)}"

    def folder(self, conversation_id: str) -> Path:
        """The conversation's folder; an ID is never used as a path as given."""
        if not _ID.fullmatch(conversation_id):
            raise InputError("There is no such saved conversation.")
        return self.directory / conversation_id

    def path(self, conversation_id: str) -> Path:
        return self.folder(conversation_id) / "conversation.json"

    def list(self) -> list[ConversationInfo]:
        """Saved conversations, most recently updated first; unreadable ones are skipped."""
        found = []
        try:
            entries = (
                sorted(self.directory.iterdir()) if self.directory.is_dir() else []
            )
        except OSError:
            raise InputError("Cannot read the saved conversations directory.") from None
        for entry in entries:
            if not _ID.fullmatch(entry.name) or entry.is_symlink():
                continue
            try:
                raw = self._bounded(entry / "meta.json", MAX_META_BYTES)
                found.append(ConversationInfo.model_validate_json(raw))
            except (OSError, ValueError):
                continue
        return sorted(found, key=lambda item: (item.updated_at, item.id), reverse=True)

    def latest(self) -> str | None:
        """Return the most recently updated conversation's ID, if there is one."""
        found = self.list()
        return found[0].id if found else None

    @staticmethod
    def _replace(path: Path, text: str) -> None:
        handle, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=".saving-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def write(
        self, conversation_id: str, data: SavedConversation, *, touch: bool = True
    ) -> None:
        """Replace a conversation atomically, readable by the user only.

        ``touch=False`` keeps the time it was last updated, for a change such
        as a new name that should not move it in the list.
        """
        folder = self.folder(conversation_id)
        updated = datetime.now(UTC)
        if not touch:
            try:
                raw = self._bounded(folder / "meta.json", MAX_META_BYTES)
                updated = ConversationInfo.model_validate_json(raw).updated_at
            except (OSError, ValueError):
                pass
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            folder.mkdir(exist_ok=True, mode=0o700)
            self._replace(
                folder / "conversation.json",
                json.dumps(data.model_dump(mode="json"), ensure_ascii=False),
            )
            info = ConversationInfo(
                id=conversation_id,
                title=data.title,
                updated_at=updated,
                turns=len(data.turns),
                artifacts=len(data.artifacts),
            )
            self._replace(folder / "meta.json", info.model_dump_json())
        except (OSError, TypeError, ValueError):
            raise InputError(
                "Cannot save the conversation; check the sessions directory."
            ) from None

    @staticmethod
    def _bounded(path: Path, max_bytes: int) -> bytes:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError
        with path.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError
        return raw

    def read(self, conversation_id: str, max_bytes: int) -> SavedConversation:
        """Load a bounded conversation written by this version."""
        path = self.path(conversation_id)
        try:
            if path.parent.is_symlink():
                raise ValueError
            raw = self._bounded(path, max_bytes)
            return SavedConversation.model_validate(json.loads(raw.decode("utf-8")))
        except FileNotFoundError:
            raise InputError("There is no such saved conversation.") from None
        except (OSError, UnicodeError, ValueError, ValidationError):
            raise InputError(
                "The saved conversation cannot be read; start a new one."
            ) from None

    def delete(self, conversation_id: str) -> None:
        """Remove a conversation's folder, including its saved artifacts."""
        folder = self.folder(conversation_id)
        try:
            if folder.is_symlink() or not folder.is_dir():
                raise InputError("There is no such saved conversation.")
            shutil.rmtree(folder)
        except OSError:
            raise InputError(
                "Cannot delete the conversation; check the sessions directory."
            ) from None
