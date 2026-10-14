"""Bounded UTF-8 context loading shared by SDK and CLI."""

import stat
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO

from sourcesift.core.config import Settings
from sourcesift.errors import InputError
from sourcesift.models import ContextDocument, Request


def read_text(stream: BinaryIO, remaining: int) -> str:
    """Read at most the remaining byte budget, rejecting oversized or binary input."""
    raw = stream.read(remaining + 1)
    if len(raw) > remaining:
        raise InputError(
            "Request exceeds limits.max_input_bytes; reduce the supplied text."
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise InputError("Context must be UTF-8 text or Markdown.") from None
    if "\x00" in text:
        raise InputError("Context contains NUL bytes; provide text or Markdown.")
    return text


def prepare_request(
    request: Request,
    settings: Settings,
    *,
    files: Sequence[str | Path] = (),
    stdin: BinaryIO | None = None,
) -> Request:
    """Combine background files, SDK context, explicit files, then optional stdin.

    The total input budget includes the prompt, context text, and context labels.
    Files must be regular files; stdin is an explicitly supplied binary stream.
    """
    budget = settings.limits.max_input_bytes
    documents: list[ContextDocument] = []

    def consume(text: str) -> None:
        nonlocal budget
        try:
            budget -= len(text.encode("utf-8"))
        except UnicodeError:
            raise InputError("Request must contain valid UTF-8 text.") from None
        if budget < 0:
            raise InputError(
                "Request exceeds limits.max_input_bytes; reduce the supplied text."
            )
        if "\x00" in text:
            raise InputError("Request contains NUL bytes; provide text or Markdown.")

    def append(document: ContextDocument) -> None:
        consume(document.name)
        consume(document.text)
        documents.append(document)

    paths = [(Path(p), "background") for p in settings.context.files]
    paths.extend((Path(p), "document") for p in files)
    if (
        len(paths) + len(request.context) + (stdin is not None)
        > settings.limits.max_context_files
    ):
        raise InputError("Too many context inputs; check limits.max_context_files.")
    consume(request.prompt)

    def load(path: Path, background: bool) -> None:
        try:
            path = path.expanduser()
            if not stat.S_ISREG(path.stat().st_mode):
                raise InputError("Context file must be a regular text file.")
            with path.open("rb") as stream:
                text = read_text(stream, budget)
        except (OSError, RuntimeError, ValueError):
            raise InputError(
                "Cannot read a context file; check the path and permissions."
            ) from None
        append(
            ContextDocument(
                name=path.name,
                text=text,
                role="background" if background else "document",
            )
        )

    for path in settings.context.files:
        load(path, True)
    for document in request.context:
        append(document)
    for path in files:
        load(Path(path), False)
    if stdin is not None:
        try:
            text = read_text(stdin, budget)
        except OSError:
            raise InputError("Cannot read standard input.") from None
        if text:
            append(ContextDocument(name="stdin", text=text))
    return Request(
        prompt=request.prompt,
        context=tuple(documents),
        output_format=request.output_format,
    )
