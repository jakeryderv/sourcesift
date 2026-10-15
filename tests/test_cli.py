"""CLI contracts for files/stdin, output streams, formats, and exit statuses."""

import io
import subprocess
import sys

import pytest

from sourcesift import ModelError, Result, Settings, cli


@pytest.fixture
def invoke(monkeypatch):
    def run(*args, stdin=b""):
        monkeypatch.setattr(sys, "argv", ["ssift", *args])
        monkeypatch.setattr(
            sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")
        )
        cli.main()

    return run


@pytest.fixture
def fake_run(monkeypatch):
    calls = []

    def run(self, request, *, files, stdin):
        calls.append(
            (self.settings, request, files, stdin.read() if stdin is not None else None)
        )
        return Result(
            answer="# Summary\n\n**Hello** world.",
            model="example/test",
            limitations=("No retrieval.",),
        )

    monkeypatch.setattr(cli.SourceSift, "run_sync", run)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda *args, **kwargs: Settings(),
    )
    return calls


def test_pipes_files_and_clean_output(invoke, fake_run, capsys):
    invoke(
        "ask",
        "summarize",
        "--file",
        "one.md",
        "--file",
        "two.md",
        stdin=b"piped context",
    )
    out = capsys.readouterr()
    assert out.err == ""
    assert out.out == "# Summary\n\n**Hello** world.\n\nNote: No retrieval.\n"
    _, request, files, stdin = fake_run[0]
    assert request.prompt == "summarize"
    assert [p.name for p in files] == ["one.md", "two.md"]
    assert stdin == b"piped context"


def test_plain_output(invoke, fake_run, capsys):
    invoke("ask", "summarize", "--format", "plain")
    out = capsys.readouterr()
    assert "Hello world." in out.out
    assert "**" not in out.out and "# " not in out.out and "\x1b" not in out.out
    assert out.err == ""


@pytest.mark.parametrize(
    "args",
    [
        ("ask",),
        ("ask", "task", "--unknown"),
        ("ask", "task", "--format", "bad"),
        ("ask", " "),
    ],
)
def test_invalid_invocation(invoke, fake_run, capsys, args):
    with pytest.raises(SystemExit) as exc:
        invoke(*args)
    assert exc.value.code == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert "ssift:" in out.err
    assert fake_run == []


def test_provider_failure(invoke, fake_run, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise ModelError("Service unavailable.")

    monkeypatch.setattr(cli.SourceSift, "run_sync", fail)
    with pytest.raises(SystemExit) as exc:
        invoke("ask", "task")
    assert exc.value.code == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == "ssift: Service unavailable.\n"


def test_terminal_stdin_is_not_read(fake_run, monkeypatch):
    class Terminal:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Terminal())
    cli.ask("task")
    assert fake_run[0][3] is None


def test_keyboard_interrupt(invoke, fake_run, monkeypatch, capsys):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.SourceSift, "run_sync", interrupt)
    with pytest.raises(SystemExit) as exc:
        invoke("ask", "task")
    assert exc.value.code == 130
    assert "Traceback" not in capsys.readouterr().err


def test_help_version_and_missing_key_subprocess(monkeypatch, tmp_path):
    for key in (
        "SOURCESIFT_CONFIG",
        "SOURCESIFT_MODEL",
        "SOURCESIFT_REASONING_EFFORT",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    # Use a selected empty config so a user's settings cannot affect this test.
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    for args, expected in [
        (["--help"], "ask"),
        (["--version"], "0."),
        (["ask", "--help"], "--file"),
    ]:
        result = subprocess.run(
            [sys.executable, "-m", "sourcesift", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0
        assert expected in result.stdout
        assert result.stderr == ""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sourcesift",
            "ask",
            "task",
            "--config",
            str(config),
            "--model",
            "example/test",
        ],
        input="text",
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "OPENROUTER_API_KEY" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_uses_shared_context_and_model(invoke, monkeypatch, tmp_path, capsys):
    import json
    from contextlib import asynccontextmanager

    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )
    from pydantic_ai.models.function import FunctionModel

    from sourcesift.agents import runtime

    captured = []

    async def respond(messages, info):
        for message in messages:
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, UserPromptPart):
                        captured.append(json.loads(part.content))
        return ModelResponse(parts=[TextPart("Combined summary")])

    @asynccontextmanager
    async def model(settings):
        assert settings.agent.model == "example/override"
        assert settings.agent.reasoning_effort == "medium"
        yield FunctionModel(respond)

    monkeypatch.setattr(runtime, "_openrouter_model", model)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("SOURCESIFT_MODEL", "example/environment")
    monkeypatch.delenv("SOURCESIFT_REASONING_EFFORT", raising=False)
    config = tmp_path / "config.toml"
    config.write_text('[context]\nfiles=["profile.md"]', encoding="utf-8")
    (tmp_path / "profile.md").write_text("background", encoding="utf-8")
    report = tmp_path / "report.md"
    report.write_text("report", encoding="utf-8")
    invoke(
        "ask",
        "task",
        "--config",
        str(config),
        "--model",
        "example/override",
        "--reasoning-effort",
        "medium",
        "--file",
        str(report),
        stdin=b"piped",
    )
    assert [d["text"] for d in captured[0]["context"]] == [
        "background",
        "report",
        "piped",
    ]
    output = capsys.readouterr()
    assert output.out.startswith("Combined summary\n")
    assert "No external sources" in output.out
    assert output.err == ""


def test_configuration_failure_exit(invoke, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        invoke("ask", "task", "--config", str(tmp_path / "missing.toml"))
    assert exc.value.code == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert "configuration file does not exist" in out.err


def test_closed_output_pipe(invoke, fake_run, monkeypatch):
    closed = []

    class ClosedPipe:
        def write(self, text):
            raise BrokenPipeError

        def fileno(self):
            return 1

    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    monkeypatch.setattr(cli.os, "dup2", lambda source, target: closed.append(target))
    with pytest.raises(SystemExit) as exc:
        invoke("ask", "task")
    assert exc.value.code == 141
    assert closed == [1]


def test_bare_terminal_opens_chat_but_help_still_works(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(sys, "argv", ["ssift"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("sourcesift.tui.ChatApp.run", lambda self: calls.append(self))
    monkeypatch.setattr(cli, "load_settings", lambda *args, **kwargs: Settings())
    cli.main()
    assert len(calls) == 1
    monkeypatch.setattr(sys, "argv", ["ssift", "--help"])
    cli.main()
    assert len(calls) == 1 and "Usage:" in capsys.readouterr().out


def test_bare_nonterminal_shows_help(invoke, capsys):
    invoke()
    assert "Usage:" in capsys.readouterr().out
