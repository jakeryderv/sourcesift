"""Composable Cyclopts CLI for single requests."""

import io
import os
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal

from cyclopts import App, CycloptsError, Parameter
from pydantic import ValidationError
from rich.console import Console
from rich.markdown import Markdown

from sourcesift import (
    ConfigurationError,
    InputError,
    Request,
    SourceSift,
    SourceSiftError,
    load_settings,
)
from sourcesift.models import Result

app = App(
    name="ssift",
    help="Research registered sources and analyze supplied text with SourceSift.",
    version=lambda: version("sourcesift"),
    exit_on_error=False,
    print_error=False,
    result_action="return_value",
)


def render_result(result: Result, output_format: Literal["markdown", "plain"]) -> str:
    """Render the answer and limitations without colors or progress output."""
    text = result.answer
    if output_format == "plain":
        buffer = io.StringIO()
        console = Console(
            file=buffer, force_terminal=False, color_system=None, width=100
        )
        console.print(Markdown(text, hyperlinks=False))
        text = buffer.getvalue().strip()
    if result.references:
        text += "\n\nReferences:\n" + "\n".join(
            f"[{ref.id}] {ref.title} — {ref.publisher} ({ref.kind.replace('_', ' ')})\n"
            f"{ref.url}\n"
            f"Published: {ref.published_at.isoformat() if ref.published_at else 'unknown'}; "
            f"updated: {ref.updated_at.isoformat() if ref.updated_at else 'unknown'}; "
            f"retrieved: {ref.retrieved_at.isoformat()}\n"
            f"Retrieved from: {ref.retrieved_from}"
            for ref in result.references
        )
    if result.limitations:
        text += "\n\n" + "\n".join(f"Note: {item}" for item in result.limitations)
    return text.rstrip() + "\n"


@app.command
def ask(
    prompt: str,
    *,
    file: Annotated[list[Path] | None, Parameter(name=("--file", "-f"))] = None,
    config: Path | None = None,
    model: str | None = None,
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"]
    | None = None,
    format: Literal["markdown", "plain"] = "markdown",
) -> None:
    """Run a request with optional files and piped UTF-8 stdin.

    Parameters:
        prompt: The task to perform.
        file: Context file; repeat for multiple files.
        config: TOML file; overrides SOURCESIFT_CONFIG and the user default.
        model: OpenRouter provider/model ID.
        reasoning_effort: Optional reasoning effort supported by the selected model.
        format: Answer format, Markdown by default.
    """
    overrides = {}
    if model is not None:
        overrides["model"] = model
    if reasoning_effort is not None:
        overrides["reasoning_effort"] = reasoning_effort
    settings = load_settings(config, overrides={"agent": overrides})
    try:
        request = Request(prompt=prompt, output_format=format)
    except ValidationError:
        raise InputError("Provide a nonempty prompt.") from None
    stdin = None if sys.stdin.isatty() else sys.stdin.buffer
    result = SourceSift(settings).run_sync(request, files=file or (), stdin=stdin)
    sys.stdout.write(render_result(result, format))
    sys.stdout.flush()


def main() -> None:
    """Run the CLI with documented exit codes and stderr diagnostics."""
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    try:
        arguments = sys.argv[1:]
        if not arguments and sys.stdin.isatty() and sys.stdout.isatty():
            arguments = ["chat"]
        app(arguments)
    except CycloptsError as exc:
        print(f"ssift: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except (ConfigurationError, InputError) as exc:
        print(f"ssift: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except SourceSiftError as exc:
        print(f"ssift: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("ssift: interrupted", file=sys.stderr)
        raise SystemExit(130) from None
    except BrokenPipeError:
        # Avoid a second failure when Python flushes stdout during shutdown.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        raise SystemExit(141) from None


@app.command
def chat(
    *,
    file: Annotated[list[Path] | None, Parameter(name=("--file", "-f"))] = None,
    config: Path | None = None,
    model: str | None = None,
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"]
    | None = None,
) -> None:
    """Open an in-memory research conversation in the terminal.

    Parameters:
        file: Context file loaded at session start; repeat for multiple files.
        config: TOML file; overrides SOURCESIFT_CONFIG and the user default.
        model: OpenRouter provider/model ID.
        reasoning_effort: Optional reasoning effort supported by the selected model.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise InputError(
            "ssift chat requires an interactive terminal; use ssift ask for pipes."
        )
    from sourcesift.tui import ChatApp

    overrides = {}
    if model is not None:
        overrides["model"] = model
    if reasoning_effort is not None:
        overrides["reasoning_effort"] = reasoning_effort
    settings = load_settings(config, overrides={"agent": overrides})
    ChatApp(SourceSift(settings).session(files=file or ())).run()
