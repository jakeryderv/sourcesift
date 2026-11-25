"""Composable Cyclopts CLI: one-off requests and the local web app."""

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
    ModelError,
    Request,
    SourceSift,
    SourceSiftError,
    artifact_from_answer,
    load_settings,
    save_artifacts,
)
from sourcesift.artifacts import new_artifact_folder
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
    if result.figures:
        # The terminal lists figures; --artifact saves their pictures.
        text += "\n\nFigures:\n" + "\n".join(
            f"- {figure.id}: {figure.title} ({figure.kind.replace('_', ' ')} chart) "
            f"[{figure.evidence_ids[0]}]"
            for figure in result.figures
        )
    if result.artifacts:
        text += "\n\nArtifacts:\n" + "\n".join(
            f"- {item.id}: {item.title}" for item in result.artifacts
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
    json: bool = False,
    artifact: bool = False,
    debug: bool = False,
) -> None:
    """Run a request with optional files and piped UTF-8 stdin.

    Parameters:
        prompt: The task to perform.
        file: Context file; repeat for multiple files.
        config: TOML file; overrides SOURCESIFT_CONFIG and the user default.
        model: OpenRouter provider/model ID.
        reasoning_effort: Optional reasoning effort supported by the selected model.
        format: Answer format, Markdown by default.
        json: Print one JSON object with the answer, references, notes, and usage.
        artifact: Also save the result as an artifact: a Quarto document with
            its references and figures, in a new folder of the artifacts directory.
        debug: On a model failure, also print the raw provider response to stderr.
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
    try:
        result = SourceSift(settings).run_sync(
            request, files=file or (), stdin=stdin, artifacts=artifact
        )
    except ModelError as exc:
        if debug and exc.detail:
            print(f"ssift: provider detail: {exc.detail}", file=sys.stderr)
        raise
    sys.stdout.write(
        result.model_dump_json(indent=2) + "\n"
        if json
        else render_result(result, format)
    )
    if artifact:
        # A document the model wrote is saved as written; otherwise the answer is kept.
        written = result.artifacts or (artifact_from_answer(request.prompt, result),)
        folder = new_artifact_folder(settings.artifacts.directory, written[0].title)
        for path in save_artifacts(folder, written, result.references, result.figures):
            # stderr keeps the path out of piped answers.
            print(f"ssift: artifact saved to {path}", file=sys.stderr)
    sys.stdout.flush()


def main() -> None:
    """Run the CLI with documented exit codes and stderr diagnostics."""
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    try:
        app(sys.argv[1:])
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
def web(
    *,
    file: Annotated[list[Path] | None, Parameter(name=("--file", "-f"))] = None,
    config: Path | None = None,
    model: str | None = None,
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"]
    | None = None,
    save: bool = True,
    continue_: Annotated[bool, Parameter(name=("--continue", "-c"))] = False,
    port: int = 0,
    browser: bool = True,
) -> None:
    """Open the research chat as a local web page with saved conversations.

    The server listens on this computer only and stops with Ctrl+C. Conversations
    and their artifacts are saved in the sessions directory unless --no-save is given.

    Parameters:
        file: Context file loaded at session start; repeat for multiple files.
        save: Save each conversation after each completed turn; --no-save keeps
            them in memory only.
        continue_: Open the most recently saved conversation first.
        config: TOML file; overrides SOURCESIFT_CONFIG and the user default.
        model: OpenRouter provider/model ID.
        reasoning_effort: Optional reasoning effort supported by the selected model.
        port: Port to listen on; by default a free one is chosen.
        browser: Open the page in the default browser.
    """
    import secrets
    import socket
    import webbrowser

    import uvicorn

    from sourcesift.web.server import create_app

    overrides = {}
    if model is not None:
        overrides["model"] = model
    if reasoning_effort is not None:
        overrides["reasoning_effort"] = reasoning_effort
    settings = load_settings(config, overrides={"agent": overrides})
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", port))
    except OSError:
        listener.close()
        raise InputError(f"Port {port} is not available; choose another.") from None
    port = listener.getsockname()[1]
    token = secrets.token_urlsafe(24)
    application = create_app(
        SourceSift(settings),
        token=token,
        hosts=(f"127.0.0.1:{port}", f"localhost:{port}"),
        files_=[str(path) for path in file or ()],
        save=save,
        resume=continue_,
    )
    url = f"http://127.0.0.1:{port}/#{token}"
    # The link is the key to this launch: anyone who has it can use the session.
    print(f"SourceSift is running at {url}\nPress Ctrl+C to stop.", flush=True)
    if browser:
        webbrowser.open(url)
    uvicorn.Server(uvicorn.Config(application, log_level="warning")).run(
        sockets=[listener]
    )
