"""Headless keyboard tests for the terminal app and its CLI entry point."""

import asyncio
import sys

import pytest
from textual.widgets import Markdown, Static, TextArea

from sourcesift import (
    AgentSettings,
    ContextSettings,
    InputError,
    ModelError,
    Result,
    SessionEvent,
    Settings,
    SourceSift,
    cli,
)
from sourcesift.tui import ChatApp, ContextScreen


@pytest.fixture
def session(tmp_path):
    profile = tmp_path / "profile.md"
    profile.write_text("I study libraries. [bold] is literal context.")
    return SourceSift(
        Settings(
            agent=AgentSettings(model="example/test", api_key="private-key"),
            context=ContextSettings(instructions_file=profile),
        )
    ).session()


def visible(app):
    return "\n".join(str(widget.content) for widget in app.query(Static))


@pytest.mark.asyncio
async def test_send_stream_context_and_new_session(session, monkeypatch):
    started, finish = asyncio.Event(), asyncio.Event()
    prompts = []

    async def run(prompt, *, on_event):
        prompts.append(prompt)
        on_event(SessionEvent(kind="reset"))
        on_event(SessionEvent(kind="draft", text="Provisional draft"))
        started.set()
        await finish.wait()
        result = Result(
            answer="**A useful answer.**",
            model="example/test",
            limitations=("No external retrieval.",),
        )
        session._turns.append((prompt, result))
        return result

    monkeypatch.setattr(session, "run", run)
    app = ChatApp(session)
    async with app.run_test(size=(100, 32)) as pilot:
        editor = app.query_one("#prompt", TextArea)
        editor.load_text("My first line\nMy second line [bold]")
        await pilot.press("ctrl+s")
        await asyncio.wait_for(started.wait(), 2)
        await pilot.pause(0.15)
        assert "Provisional draft" in visible(app)
        editor.load_text("Next prompt")
        await pilot.press("ctrl+s", "ctrl+n")
        assert prompts == ["My first line\nMy second line [bold]"]
        assert editor.text == "Next prompt"
        await pilot.press("ctrl+k")
        assert isinstance(app.screen, ContextScreen)
        assert "libraries" in visible(app.screen)
        assert "private-key" not in visible(app.screen)
        await pilot.press("escape")
        assert not isinstance(app.screen, ContextScreen)
        finish.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.query(Markdown)
        assert "Provisional draft" not in visible(app)
        assert "No external retrieval" in visible(app)
        await pilot.press("ctrl+n")
        assert len(session.turns) == 0
        assert not app.query(Markdown)
        assert "context reloaded" in visible(app)


@pytest.mark.asyncio
async def test_cancel_and_recover(session, monkeypatch):
    started = asyncio.Event()

    async def run(prompt, *, on_event):
        on_event(SessionEvent(kind="draft", text="Discard this draft"))
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(session, "run", run)
    app = ChatApp(session)
    async with app.run_test() as pilot:
        app.query_one("#prompt", TextArea).load_text("Research")
        await pilot.press("ctrl+s")
        await asyncio.wait_for(started.wait(), 2)
        await pilot.press("escape")
        await pilot.pause()
        assert "Cancelled" in visible(app) and "Discard this draft" not in visible(app)
        assert not app._turn_active and not session.turns

        async def recover(prompt, *, on_event):
            return Result(answer="Recovered", model="example/test")

        monkeypatch.setattr(session, "run", recover)
        app.query_one("#prompt", TextArea).load_text("Try again")
        await pilot.press("ctrl+s")
        await app.workers.wait_for_complete()
        assert app.query(Markdown)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [ModelError("Service unavailable."), RuntimeError("private-key provider body")],
)
async def test_turn_error_is_safe(session, monkeypatch, failure):
    async def fail(prompt, *, on_event):
        raise failure

    monkeypatch.setattr(session, "run", fail)
    app = ChatApp(session)
    async with app.run_test(size=(60, 24)) as pilot:
        app.query_one("#prompt", TextArea).load_text("Research")
        await pilot.press("ctrl+s")
        await app.workers.wait_for_complete()
        assert "Turn failed" in visible(app)
        assert "private-key" not in visible(app)
        assert not app._turn_active


@pytest.mark.asyncio
async def test_commands_and_context_reload_failure(session, monkeypatch):
    app = ChatApp(session)
    async with app.run_test() as pilot:
        editor = app.query_one("#prompt", TextArea)
        await pilot.press("ctrl+s", "escape")
        for command in ["/help", "/unknown", "/context", "/new"]:
            editor.load_text(command)
            await pilot.press("ctrl+s")
            if command == "/context":
                await pilot.press("escape")

        def fail():
            raise InputError("Cannot read a context file.")

        monkeypatch.setattr(session, "reset", fail)
        await pilot.press("ctrl+n")
        assert "Cannot read" in visible(app)
        editor.load_text("/quit")
        await pilot.press("ctrl+s")


@pytest.mark.asyncio
async def test_empty_context_screen_and_quit():
    app = ChatApp(SourceSift(Settings()).session())
    async with app.run_test() as pilot:
        await pilot.press("ctrl+k")
        assert "No context files" in visible(app.screen)
        await pilot.press("escape", "ctrl+q")


def test_chat_rejects_pipes(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(InputError, match="interactive terminal"):
        cli.chat()


def test_chat_resolves_settings_and_launches(session, monkeypatch, tmp_path):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-key")
    monkeypatch.setattr(ChatApp, "run", lambda self: captured.append(self.session))
    captured = []
    config = tmp_path / "config.toml"
    config.write_text("")
    cli.chat(
        config=config,
        model="example/override",
        reasoning_effort="medium",
        file=[session.settings.context.instructions_file],
    )
    assert captured[0].settings.agent.model == "example/override"
    assert captured[0].settings.agent.reasoning_effort == "medium"
    assert captured[0].context[0].name == "profile.md"
