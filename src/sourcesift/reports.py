"""Markdown reports written by the application, never by the model.

The model has no file tool. A report is a rendering of one validated ``Result``
that the user explicitly asked to save, placed in the configured reports directory.
Visuals are written as tables and lists; an interface that can draw a chart may
supply it as a PNG image, saved beside the report.
"""

import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_path

from sourcesift.data import Block, Cell, Column, Figure, StatView, TableView
from sourcesift.errors import InputError
from sourcesift.models import Reference, Result

MAX_IMAGE_BYTES = 4_000_000
MAX_DATA_ROWS = 30
_PNG = b"\x89PNG\r\n\x1a\n"


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


def _number(value: float, unit: str = "") -> str:
    text = f"{value:,.4f}".rstrip("0").rstrip(".")
    if unit in {"USD", "$"}:
        return f"${text}"
    return text + (unit if unit == "%" or unit.startswith("°") else f" {unit}".rstrip())


def _table(columns: tuple[Column, ...], rows: tuple[tuple[Cell, ...], ...]) -> str:
    """A Markdown table; units go in the header so cells stay plain values."""

    def cell(value: Cell) -> str:
        if value is None:
            return ""
        return _number(value) if isinstance(value, int | float) else _line(value)

    heads = [_line(f"{c.name} ({c.unit})" if c.unit else c.name) for c in columns]
    numeric = [
        any(isinstance(row[i], int | float) for row in rows) for i in range(len(heads))
    ]
    lines = [
        "| " + " | ".join(heads) + " |",
        "| " + " | ".join("---:" if n else "---" for n in numeric) + " |",
        *("| " + " | ".join(cell(value) for value in row) + " |" for row in rows),
    ]
    return "\n".join(lines)


def _visual(block: Block, image: str | None) -> str:
    view = block.view
    cited = " ".join(f"[{item}]" for item in block.evidence_ids)
    parts = [f"### {_line(view.title) or 'Visual'}"]
    if isinstance(view, TableView):
        parts.append(_table(view.columns, view.rows))
    elif isinstance(view, StatView):
        items = []
        for item in view.items:
            shown = (
                _number(item.value, item.unit)
                if isinstance(item.value, int | float)
                else _line(item.value)
            )
            change = (
                f" (change: {_number(item.change, item.unit)})"
                if item.change is not None
                else ""
            )
            items.append(f"- **{_line(item.label)}:** {shown}{change}")
        parts.append("\n".join(items))
    elif isinstance(view, Figure) and image:
        parts.append(f"![{_line(view.title)}]({image})")
    else:
        # No picture was supplied, so give the rows the figure was drawn from.
        rows = block.table.rows
        note = "The chart is not included in this report. It was drawn from "
        note += (
            f"the first {MAX_DATA_ROWS} of {len(rows)} rows below."
            if len(rows) > MAX_DATA_ROWS
            else "these rows."
        )
        parts += [f"*{note}*", _table(block.table.columns, rows[:MAX_DATA_ROWS])]
    parts.append(f"Data from {cited}." if cited else "")
    return "\n\n".join(part for part in parts if part)


def render_report(
    prompt: str,
    result: Result,
    *,
    generated_at: datetime | None = None,
    images: Mapping[int, str] | None = None,
) -> str:
    """Render a request and its result as a self-contained Markdown document.

    The answer is included as the model wrote it. Titles, publishers, and notes
    come from retrieved pages, so they are flattened and escaped. ``images`` maps
    a position in ``result.blocks`` to the file name of a picture of that visual.
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
    if result.blocks:
        named = images or {}
        sections.append(
            "## Visuals\n\n"
            + "\n\n".join(
                _visual(block, named.get(i)) for i, block in enumerate(result.blocks)
            )
        )
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
    images: Mapping[int, bytes] | None = None,
) -> Path:
    """Write a new report file and return its path; existing files are never replaced.

    The name is ``<UTC timestamp>-<words from the prompt>.md``. ``directory``
    defaults to the per-user reports directory and is created when missing.
    ``images`` maps a position in ``result.blocks`` to PNG bytes for that chart or
    map; each is saved beside the report as ``<report name>-<n>.png`` and linked
    from it. Anything that is not a PNG of a figure is left out.
    """
    generated = generated_at or datetime.now(UTC)
    slug = "-".join(re.findall(r"[a-z0-9]+", prompt.lower()))[:48].strip("-")
    stem = generated.astimezone(UTC).strftime("%Y%m%d-%H%M%S") + (
        f"-{slug}" if slug else ""
    )
    pictures = {
        index: data
        for index, data in (images or {}).items()
        if 0 <= index < len(result.blocks)
        and isinstance(result.blocks[index].view, Figure)
        and data.startswith(_PNG)
        and len(data) <= MAX_IMAGE_BYTES
    }
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
                saved = {}
                for index, data in sorted(pictures.items()):
                    name = f"{path.stem}-{index + 1}.png"
                    try:
                        image = os.open(
                            folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
                        )
                    except FileExistsError:
                        continue
                    with os.fdopen(image, "wb") as picture:
                        picture.write(data)
                    saved[index] = name
                stream.write(
                    render_report(prompt, result, generated_at=generated, images=saved)
                )
            return path.resolve()
    except OSError:
        raise InputError(
            "Cannot write the report; check the reports directory."
        ) from None
    raise InputError("Cannot choose an unused report name; try again.")
