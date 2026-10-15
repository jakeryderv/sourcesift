"""Headless keyboard tests for the terminal app and its CLI entry point."""

import asyncio
import sys

import pytest
from textual import events
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
async def test_multiline_keys_paste_and_modal_do_not_submit(session, monkeypatch):
    prompts = []

    async def respond(prompt, *, on_event):
        prompts.append(prompt)
        return Result(answer="Done", model="example/test")

    monkeypatch.setattr(session, "run", respond)
    app = ChatApp(session)
    async with app.run_test() as pilot:
        editor = app.query_one("#prompt", TextArea)
        await pilot.press("a", "shift+enter", "b", "alt+enter", "c", "ctrl+j", "d")
        assert editor.text == "a\nb\nc\nd"
        assert prompts == []
        app.post_message(events.Paste("\npasted\nlines"))
        await pilot.pause()
        assert editor.text == "a\nb\nc\nd\npasted\nlines"
        assert prompts == []
        app.action_show_context()
        await pilot.pause()
        await pilot.press("enter", "shift+enter")
        assert prompts == []
        await pilot.press("escape", "enter")
        await app.workers.wait_for_complete()
        assert prompts == ["a\nb\nc\nd\npasted\nlines"]
        assert editor.text == ""


@pytest.mark.asyncio
async def test_cancel_before_worker_starts_then_send_again(session, monkeypatch):
    prompts = []

    async def respond(prompt, *, on_event):
        prompts.append(prompt)
        return Result(answer="Recovered", model="example/test")

    monkeypatch.setattr(session, "run", respond)
    app = ChatApp(session)
    async with app.run_test() as pilot:
        app.query_one("#prompt", TextArea).load_text("Cancel immediately")
        await app.action_send()
        # No event-loop yield between scheduling the worker and cancellation.
        app.action_cancel_turn()
        await pilot.pause()
        assert not app._turn_active and prompts == []
        assert "Cancelled" in visible(app)
        app.query_one("#prompt", TextArea).load_text("Try again")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        assert prompts == ["Try again"] and app.query(Markdown)


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
        await pilot.press("enter")
        await asyncio.wait_for(started.wait(), 2)
        await pilot.pause(0.15)
        assert "Provisional draft" in visible(app)
        editor.load_text("Next prompt")
        await pilot.press("enter")
        assert prompts == ["My first line\nMy second line [bold]"]
        assert editor.text == "Next prompt"
        editor.load_text("/context")
        await pilot.press("enter")
        assert isinstance(app.screen, ContextScreen)
        assert "libraries" in visible(app.screen)
        assert "private-key" not in visible(app.screen)
        await pilot.press("escape")
        assert not isinstance(app.screen, ContextScreen)
        editor.load_text("/new")
        await pilot.press("enter")
        assert "Cancel the active turn" in visible(app)
        finish.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.query(Markdown)
        assert "Provisional draft" not in visible(app)
        assert "No external retrieval" in visible(app)
        editor.load_text("/new")
        await pilot.press("enter")
        assert len(session.turns) == 0
        assert not app.query(Markdown)
        assert "context reloaded" in visible(app)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", ["escape", "/cancel"])
async def test_cancel_and_recover(session, monkeypatch, cancel):
    started = asyncio.Event()

    async def run(prompt, *, on_event):
        on_event(SessionEvent(kind="draft", text="Discard this draft"))
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(session, "run", run)
    app = ChatApp(session)
    async with app.run_test() as pilot:
        app.query_one("#prompt", TextArea).load_text("Research")
        await pilot.press("enter")
        await asyncio.wait_for(started.wait(), 2)
        if cancel == "/cancel":
            app.query_one("#prompt", TextArea).load_text(cancel)
            await pilot.press("enter")
        else:
            await pilot.press(cancel)
        await pilot.pause()
        assert "Cancelled" in visible(app) and "Discard this draft" not in visible(app)
        assert not app._turn_active and not session.turns

        async def recover(prompt, *, on_event):
            return Result(answer="Recovered", model="example/test")

        monkeypatch.setattr(session, "run", recover)
        app.query_one("#prompt", TextArea).load_text("Try again")
        await pilot.press("enter")
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
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        assert "Turn failed" in visible(app)
        assert "private-key" not in visible(app)
        assert not app._turn_active


@pytest.mark.asyncio
async def test_commands_and_context_reload_failure(session, monkeypatch):
    app = ChatApp(session)
    async with app.run_test() as pilot:
        editor = app.query_one("#prompt", TextArea)
        await pilot.press("enter", "escape")
        for command in ["/help", "/unknown", "/context", "/cancel", "/new"]:
            editor.load_text(command)
            await pilot.press("enter")
            if command == "/context":
                await pilot.press("escape")

        def fail():
            raise InputError("Cannot read a context file.")

        monkeypatch.setattr(session, "reset", fail)
        editor.load_text("/new")
        await pilot.press("enter")
        assert "Cannot read" in visible(app)
        editor.load_text("/quit")
        await pilot.press("enter")


@pytest.mark.asyncio
async def test_empty_context_screen_and_quit():
    app = ChatApp(SourceSift(Settings()).session())
    async with app.run_test() as pilot:
        app.query_one("#prompt", TextArea).load_text("/context")
        await pilot.press("enter")
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
