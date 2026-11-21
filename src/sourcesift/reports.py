"""Markdown reports written by the application, never by the model.

The model has no file tool. A report is a rendering of one validated ``Result``
that the user explicitly asked to save, placed in the configured reports directory.
"""

import os
import re
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_path

from sourcesift.errors import InputError
from sourcesift.models import Reference, Result


def default_reports_path() -> Path:
    """Return the platform's per-user SourceSift reports directory."""
    return user_data_path("sourcesift", appauthor=False) / "reports"


def _line(text: str) -> str:
    """Flatten retrieved or user text to one line that cannot start a Markdown block."""
    return re.sub(r"([\[\]<>`*_#|\\])", r"\\\1", " ".join(text.split()))


def _date(value: datetime | None) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC") if value else "unknown"


def _reference(ref: Reference) -> str:
    kind = ref.kind.replace("_", " ")
    dates = (
        f"Published: {_date(ref.published_at)}; updated: {_date(ref.updated_at)}; "
        f"retrieved: {_date(ref.retrieved_at)}"
    )
    lines = [
        f"- **{ref.id}** {_line(ref.title)} — {_line(ref.publisher)} ({kind})",
        # Angle brackets keep URLs with parentheses or underscores intact.
        f"  <{ref.url}>",
        f"  {dates}",
    ]
    lines.extend(f"  Note: {_line(note)}" for note in ref.limitations)
    return "  \n".join(lines)


def render_report(
    prompt: str, result: Result, *, generated_at: datetime | None = None
) -> str:
    """Render a request and its result as a self-contained Markdown document.

    The answer is included as the model wrote it. Titles, publishers, and notes
    come from retrieved pages, so they are flattened and escaped.
    """
    generated = generated_at or datetime.now(UTC)
    title = _line(prompt)
    title = title if len(title) <= 80 else title[:79].rstrip() + "…"
    quoted = "\n".join("> " + line for line in prompt.strip().splitlines())
    header = [
        f"- Generated: {_date(generated)}",
        f"- Model: {_line(result.model) or 'unknown'}",
    ]
    if result.selected_sources:
        header.append(f"- Sources read: {_line(', '.join(result.selected_sources))}")
    if result.window:
        start = _date(result.window.start) if result.window.start else "unbounded"
        header.append(
            f"- Date window: {start} to {_date(result.window.end)} "
            f"({result.window.label.replace('_', ' ')})"
        )
    sections = [
        f"# {title}",
        "\n".join(header),
        f"## Request\n\n{quoted}",
        f"## Answer\n\n{result.answer.strip()}",
    ]
    if result.references:
        sections.append(
            "## References\n\n" + "\n".join(_reference(r) for r in result.references)
        )
    if result.limitations:
        sections.append(
            "## Notes\n\n" + "\n".join(f"- {_line(n)}" for n in result.limitations)
        )
    return "\n\n".join(sections) + "\n"


def save_report(
    prompt: str,
    result: Result,
    directory: str | Path | None = None,
    *,
    generated_at: datetime | None = None,
) -> Path:
    """Write a new report file and return its path; existing files are never replaced.

    The name is ``<UTC timestamp>-<words from the prompt>.md``. ``directory``
    defaults to the per-user reports directory and is created when missing.
    """
    generated = generated_at or datetime.now(UTC)
    slug = "-".join(re.findall(r"[a-z0-9]+", prompt.lower()))[:48].strip("-")
    stem = generated.astimezone(UTC).strftime("%Y%m%d-%H%M%S") + (
        f"-{slug}" if slug else ""
    )
    text = render_report(prompt, result, generated_at=generated)
    try:
        folder = Path(
            directory if directory is not None else default_reports_path()
        ).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, 100):
            path = folder / f"{stem}{'' if attempt == 1 else f'-{attempt}'}.md"
            try:
                # Exclusive creation: neither overwrite nor follow an existing link.
                handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                continue
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
            return path.resolve()
    except OSError:
        raise InputError(
            "Cannot write the report; check the reports directory."
        ) from None
    raise InputError("Cannot choose an unused report name; try again.")
