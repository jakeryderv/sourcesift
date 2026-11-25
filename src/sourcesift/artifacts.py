"""Artifacts: documents the agent writes, saved as Quarto Markdown.

An artifact is Markdown with ``[S1]`` citations and figures placed by ID. The
model writes it through one tool and has no file tool: the application checks
the text, then writes the files itself. A saved artifact is a ``.qmd`` file with
no executable code, a ``references.json`` bibliography built from the retrieved
evidence, a ``references.csl`` style that numbers citations, and a ``figures`` folder of pictures with the recipe for each.
"""

import json
import os
import re
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_path

from sourcesift.data import Figure
from sourcesift.errors import InputError
from sourcesift.figures import render_png
from sourcesift.models import Artifact, Reference, Result

CITATION = re.compile(r"\[S(\d+)\]")
# A figure is placed with a Markdown image whose target is its ID: ![Title](F1)
FIGURE = re.compile(r"!\[[^\]\n]*\]\(\s*(F[1-9]\d*)\s*\)")
_IMAGE = re.compile(r"!\[[^\]\n]*\]\(([^)\n]*)\)")
_CITED_RUN = re.compile(r"\[S\d+\](?:[ \t]*,?[ \t]*\[S\d+\])*")
_PLACED = re.compile(r"(!\[[^\]\n]*\]\()\s*(F[1-9]\d*)\s*(\))")
# Quarto and Pandoc syntax that runs code, reads files, or passes raw markup through.
_FORBIDDEN = (
    (re.compile(r"^[ \t]*(?:`{3,}|~{3,})[ \t]*\{", re.MULTILINE), "code cells ({python}, {r}, ...)"),
    (re.compile(r"`\{[A-Za-z]"), "inline code that runs"),
    (re.compile(r"\{\{<"), "shortcodes ({{< ... >}})"),
    (re.compile(r"\{="), "raw markup blocks ({=html}, {=latex}, ...)"),
)  # fmt: skip
MAX_ARTIFACTS = 12
# How an exported file prints citations: [1] in the text and a numbered list in
# the order first cited, matching the numbered chips in the web app.
REFERENCE_STYLE = """<?xml version="1.0" encoding="utf-8"?>
<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0" default-locale="en-US">
  <info>
    <title>SourceSift numbered references</title>
    <id>https://github.com/jakeryderv/sourcesift/numbered-references</id>
    <updated>2026-11-25T00:00:00+00:00</updated>
  </info>
  <citation collapse="citation-number">
    <sort>
      <key variable="citation-number"/>
    </sort>
    <layout prefix="[" suffix="]" delimiter=", ">
      <text variable="citation-number"/>
    </layout>
  </citation>
  <bibliography second-field-align="flush" entry-spacing="0">
    <layout suffix=".">
      <text variable="citation-number" prefix="[" suffix="]"/>
      <group delimiter=". ">
        <names variable="author">
          <name/>
        </names>
        <text variable="title"/>
        <text variable="container-title"/>
        <date variable="issued" form="text" prefix="Published "/>
        <text variable="URL"/>
        <date variable="accessed" form="text" prefix="Retrieved "/>
      </group>
    </layout>
  </bibliography>
</style>
"""
EXPORT_FORMATS = {
    # name -> (Quarto --to value, file extension, label)
    "html": ("html", "html", "Web page"),
    "pdf": ("typst", "pdf", "PDF"),
    "docx": ("docx", "docx", "Word"),
    "slides": ("revealjs", "html", "Slides"),
}


def default_artifacts_path() -> Path:
    """Return the platform's per-user SourceSift artifacts directory."""
    return user_data_path("sourcesift", appauthor=False) / "artifacts"


def citations_in(text: str) -> set[str]:
    return {"S" + value for value in CITATION.findall(text)}


def artifact_problem(
    title: str,
    markdown: str,
    *,
    evidence_ids: Iterable[str],
    figure_ids: Iterable[str],
    max_chars: int,
) -> str | None:
    """Why this text cannot be an artifact, worded for the model; ``None`` if it can."""
    if not title.strip():
        return "Give the artifact a title."
    if not markdown.strip():
        return "The artifact has no text."
    if len(markdown) > max_chars:
        return f"The artifact is longer than {max_chars} characters; shorten it."
    if markdown.lstrip().startswith("---"):
        return "Do not write a YAML header; the application adds the title and date."
    for pattern, name in _FORBIDDEN:
        if pattern.search(markdown):
            return f"An artifact cannot contain {name}. Write plain Markdown."
    unknown = citations_in(markdown) - set(evidence_ids)
    if unknown:
        return "Cite only existing evidence IDs; unknown: " + ", ".join(sorted(unknown))
    known = set(figure_ids)
    for target in _IMAGE.findall(markdown):
        if target.strip() not in known:
            return (
                "The only images an artifact can contain are figures that "
                "make_figure returned, placed as ![Title](F1)."
            )
    return None


def title_from(prompt: str) -> str:
    """A one-line title from a request."""
    text = " ".join(prompt.split())
    return (text if len(text) <= 80 else text[:79].rstrip() + "…") or "Untitled"


def artifact_from_answer(
    prompt: str, result: Result, *, artifact_id: str = "A1", now: datetime | None = None
) -> Artifact:
    """Turn a finished answer into an artifact, keeping its citations and figures."""
    text = result.answer.strip()
    title = title_from(prompt)
    heading = re.match(r"#{1,6}[ \t]+(.+?)[ \t#]*\n+(?=\S)", text)
    if heading:
        # The answer names itself; the request would repeat above that heading.
        title, text = title_from(heading[1].replace("*", "")), text[heading.end() :]
    return Artifact(
        id=artifact_id,
        title=title,
        markdown=text,
        notes=result.limitations,
        updated_at=now or datetime.now(UTC),
    )


def _slug(text: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", text.lower()))[:48].strip("-")


def artifact_filename(artifact: Artifact) -> str:
    """The artifact's file name: its ID, then words from its title."""
    slug = _slug(artifact.title)
    return f"{artifact.id}{'-' + slug if slug else ''}.qmd"


def _date_parts(value: datetime) -> dict[str, list[list[int]]]:
    moment = value.astimezone(UTC)
    return {"date-parts": [[moment.year, moment.month, moment.day]]}


def csl_reference(ref: Reference) -> dict[str, object]:
    """One reference as CSL JSON, the bibliography format Quarto reads."""
    entry: dict[str, object] = {
        "id": ref.id,
        "type": "webpage",
        "title": " ".join(ref.title.split()),
        "URL": ref.url,
        "container-title": ref.publisher,
        "accessed": _date_parts(ref.retrieved_at),
    }
    if ref.author:
        entry["author"] = [{"literal": " ".join(ref.author.split())}]
    dated = ref.published_at or ref.updated_at
    if dated:
        entry["issued"] = _date_parts(dated)
    notes = [ref.kind.replace("_", " "), *ref.limitations]
    entry["note"] = " ".join(note.rstrip(".") + "." for note in notes)
    return entry


def _line(text: str) -> str:
    """Flatten retrieved or user text to one line that cannot start a Markdown block."""
    return re.sub(r"([\[\]<>`*_#|\\@{}])", r"\\\1", " ".join(text.split()))


def render_qmd(artifact: Artifact, *, references: bool = True) -> str:
    """The artifact as a Quarto document that runs no code.

    ``[S1]`` becomes the Quarto citation ``[@S1]``, resolved from
    ``references.json`` beside the file, and a placed figure points at its
    picture in ``figures/``. The header turns code execution off and stops raw
    HTML and LaTeX from passing through to an exported file.
    """
    body = artifact.markdown.strip()
    # A line of dashes could open a YAML block inside the text; this is the same rule.
    body = re.sub(r"^[ \t]*-{3,}[ \t]*$", "***", body, flags=re.MULTILINE)
    body = _CITED_RUN.sub(
        lambda run: (
            "[" + "; ".join("@S" + number for number in CITATION.findall(run[0])) + "]"
        ),
        body,
    )
    body = _PLACED.sub(lambda m: f"{m[1]}figures/{m[2]}.png{m[3]}", body)
    header = [
        "---",
        "title: " + json.dumps(artifact.title, ensure_ascii=False),
        "date: " + artifact.updated_at.astimezone(UTC).strftime("%Y-%m-%d"),
        "execute:",
        "  enabled: false",
        "from: markdown-raw_html-raw_tex-raw_attribute",
    ]
    if references:
        header += [
            "bibliography: references.json",
            "csl: references.csl",
            "link-citations: true",
        ]
    header += [
        "format:",
        "  html:",
        "    embed-resources: true",
        "  revealjs:",
        "    embed-resources: true",
        "  typst:",
        "    citeproc: true",
        "---",
    ]
    sections = ["\n".join(header), body]
    if artifact.notes:
        sections.append(
            "## Notes\n\n" + "\n".join(f"- {_line(note)}" for note in artifact.notes)
        )
    if references:
        sections.append("## References\n\n::: {#refs}\n:::")
    return "\n\n".join(sections) + "\n"


def _write(path: Path, data: bytes) -> None:
    """Replace a file atomically without following a link left in its place."""
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".saving-")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def save_artifacts(
    directory: str | Path,
    artifacts: Iterable[Artifact],
    references: Iterable[Reference],
    figures: Iterable[Figure],
) -> list[Path]:
    """Write artifacts, their bibliography, and their figures into one folder.

    The folder gets ``<ID>-<title>.qmd`` for each artifact, ``references.json``
    for the references any of them cites with ``references.csl`` to number them, and ``figures/<ID>.png`` with
    ``figures/<ID>.json`` (the recipe and rows) for each figure any of them
    places. Files from an earlier call are replaced, so saving again after a
    revision updates the folder. Returns the artifact files' paths.
    """
    wanted = list(artifacts)
    text = "\n".join(item.markdown for item in wanted)
    cited = citations_in(text)
    placed = set(FIGURE.findall(text))
    used_figures = [figure for figure in figures if figure.id in placed]
    cited.update(figure.evidence_ids[0] for figure in used_figures)
    used = [ref for ref in references if ref.id in cited]
    try:
        folder = Path(directory).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for artifact in wanted:
            # A retitled artifact keeps one file: earlier names for its ID go.
            for stale in folder.glob(f"{artifact.id}-*.qmd"):
                stale.unlink()
            (folder / f"{artifact.id}.qmd").unlink(missing_ok=True)
            path = folder / artifact_filename(artifact)
            _write(path, render_qmd(artifact, references=bool(used)).encode())
            paths.append(path.resolve())
        if used:
            listing = json.dumps(
                [csl_reference(ref) for ref in used], ensure_ascii=False, indent=2
            )
            _write(folder / "references.json", listing.encode())
            _write(folder / "references.csl", REFERENCE_STYLE.encode())
        if used_figures:
            (folder / "figures").mkdir(exist_ok=True)
        for figure in used_figures:
            _write(folder / "figures" / f"{figure.id}.png", render_png(figure))
            recipe = figure.model_dump_json(indent=2)
            _write(folder / "figures" / f"{figure.id}.json", recipe.encode())
        return paths
    except OSError:
        raise InputError(
            "Cannot write the artifact; check the artifacts directory."
        ) from None


def new_artifact_folder(
    directory: str | Path | None, title: str, *, now: datetime | None = None
) -> Path:
    """A new, unused folder named by UTC time and words from the title."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    slug = _slug(title)
    stem = moment.strftime("%Y%m%d-%H%M%S") + (f"-{slug}" if slug else "")
    try:
        parent = Path(
            directory if directory is not None else default_artifacts_path()
        ).expanduser()
        parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, 100):
            folder = parent / f"{stem}{'' if attempt == 1 else f'-{attempt}'}"
            try:
                folder.mkdir()
            except FileExistsError:
                continue
            return folder.resolve()
    except OSError:
        raise InputError(
            "Cannot write the artifact; check the artifacts directory."
        ) from None
    raise InputError("Cannot choose an unused artifact folder name; try again.")
