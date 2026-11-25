"""Export a saved artifact to other formats with Quarto, when it is installed.

Quarto is optional. Without it an artifact is still a ``.qmd`` file that opens as
Markdown anywhere; with it the same file renders to a web page, PDF, Word
document, or slides. Rendering runs no code: the file turns execution off and
contains no cells.
"""

import shutil
import subprocess
from pathlib import Path

from sourcesift.artifacts import EXPORT_FORMATS
from sourcesift.errors import InputError

EXPORT_TIMEOUT_SECONDS = 120


def quarto_path() -> str | None:
    """Where the ``quarto`` program is, or ``None`` when it is not installed."""
    return shutil.which("quarto")


def export_formats() -> tuple[str, ...]:
    """The formats ``export_artifact`` can produce on this computer."""
    return tuple(EXPORT_FORMATS) if quarto_path() else ()


def export_artifact(path: str | Path, format: str) -> Path:
    """Render a saved ``.qmd`` artifact and return the new file beside it.

    ``format`` is ``html``, ``pdf``, ``docx``, or ``slides``. The file must be one
    that ``save_artifacts`` wrote, with its ``references.json`` and ``figures``
    folder in place.
    """
    source = Path(path)
    if format not in EXPORT_FORMATS:
        raise InputError("Export format must be one of: " + ", ".join(EXPORT_FORMATS))
    program = quarto_path()
    if program is None:
        raise InputError("Exporting needs Quarto; install it from https://quarto.org.")
    if source.suffix != ".qmd" or not source.is_file():
        raise InputError("There is no such artifact file to export.")
    target, extension, _ = EXPORT_FORMATS[format]
    name = f"{source.stem}{'-slides' if format == 'slides' else ''}.{extension}"
    try:
        done = subprocess.run(
            [program, "render", source.name, "--to", target, "--output", name],
            cwd=source.parent,
            capture_output=True,
            timeout=EXPORT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise InputError("Quarto took too long to export the artifact.") from None
    except OSError:
        raise InputError("Quarto could not be started.") from None
    output = source.parent / name
    if done.returncode != 0 or not output.is_file():
        detail = " ".join(done.stderr.decode(errors="replace").split())[-300:]
        raise InputError(f"Quarto could not export the artifact. {detail}".strip())
    return output
