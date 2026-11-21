"""Opt-in conversation files. Nothing is written unless saving is requested.

A saved conversation holds prompts, answers, retrieved evidence text, and the
text of any attached documents, so files are private to the user. Credentials
and settings are never saved.
"""

import json
import os
import secrets
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from platformdirs import user_data_path
from pydantic import ValidationError

from sourcesift.errors import InputError
from sourcesift.models import ContextDocument, Contract, Evidence, Result


class SavedTurn(Contract):
    """One completed prompt and its validated result."""

    prompt: str
    result: Result


class SavedConversation(Contract):
    """The file format; a different ``version`` is rejected rather than guessed at."""

    version: Literal[1] = 1
    model: str | None = None
    # Model framework messages, validated by the session when it resumes.
    messages: list[Any]
    evidence: tuple[Evidence, ...]
    next_id: int
    limitations: tuple[str, ...]
    turns: tuple[SavedTurn, ...]
    context: tuple[ContextDocument, ...]


def default_sessions_path() -> Path:
    """Return the platform's per-user SourceSift conversations directory."""
    return user_data_path("sourcesift", appauthor=False) / "sessions"


class SessionStore:
    """One JSON file per conversation in a private directory."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(
            directory if directory is not None else default_sessions_path()
        ).expanduser()

    def new_path(self) -> Path:
        """Name a conversation by its UTC start time plus a random suffix."""
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return self.directory / f"{stamp}-{secrets.token_hex(4)}.json"

    def latest(self) -> Path | None:
        """Return the most recently saved conversation, if there is one."""
        try:
            files = [
                (entry.stat().st_mtime_ns, entry.name, entry)
                for entry in self.directory.glob("*.json")
                if entry.is_file() and not entry.is_symlink()
            ]
        except OSError:
            raise InputError("Cannot read the saved conversations directory.") from None
        return max(files)[2] if files else None

    def write(self, path: Path, data: SavedConversation) -> None:
        """Replace a conversation file atomically, readable by the user only."""
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            handle, temporary = tempfile.mkstemp(
                dir=self.directory, prefix=".saving-", suffix=".tmp"
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(data.model_dump(mode="json"), stream, ensure_ascii=False)
                os.replace(temporary, path)
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                raise
        except (OSError, TypeError, ValueError):
            raise InputError(
                "Cannot save the conversation; check the sessions directory."
            ) from None

    def read(self, path: Path, max_bytes: int) -> SavedConversation:
        """Load a bounded conversation file written by this version."""
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError
            with path.open("rb") as stream:
                raw = stream.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise ValueError
            return SavedConversation.model_validate(json.loads(raw.decode("utf-8")))
        except (OSError, UnicodeError, ValueError, ValidationError):
            raise InputError(
                "The saved conversation cannot be read; start a new one."
            ) from None
