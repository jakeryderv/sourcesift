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
        await pilot.press("enter", "enter")
        assert isinstance(app.screen, ContextScreen)
        assert "libraries" in visible(app.screen)
        assert "private-key" not in visible(app.screen)
        await pilot.press("escape")
        assert not isinstance(app.screen, ContextScreen)
        editor.load_text("/new")
        await pilot.press("enter", "enter")
        assert "Cancel the active turn" in visible(app)
        finish.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.query(Markdown)
        assert "Provisional draft" not in visible(app)
        assert "No external retrieval" in visible(app)
        editor.load_text("/new")
        await pilot.press("enter", "enter")
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
            await pilot.press("enter", "enter")
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
            await pilot.press("escape", "enter")
            if command in {"/context", "/help"}:
                await pilot.press("escape")

        def fail():
            raise InputError("Cannot read a context file.")

        monkeypatch.setattr(session, "reset", fail)
        editor.load_text("/new")
        await pilot.press("enter", "enter")
        assert "Cannot read" in visible(app)
        editor.load_text("/quit")
        await pilot.press("enter", "enter")


@pytest.mark.asyncio
async def test_empty_context_screen_and_quit():
    app = ChatApp(SourceSift(Settings()).session())
    async with app.run_test() as pilot:
        await pilot.press("escape")  # Close initial model setup.
        app.query_one("#prompt", TextArea).load_text("/context")
        await pilot.press("enter", "enter")
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


@pytest.mark.asyncio
async def test_fuzzy_command_picker_accept_dismiss_and_help(session):
    from textual.widgets import OptionList

    from sourcesift.tui_panels import HelpScreen

    app = ChatApp(session)
    async with app.run_test() as pilot:
        editor = app.query_one("#prompt", TextArea)
        await pilot.press("/", "c", "t", "x")
        popup = app.query_one("#completions", OptionList)
        assert popup.display and app._matches == ["/context"]
        await pilot.press("enter")
        assert editor.text == "/context"
        assert not popup.display and not isinstance(app.screen, ContextScreen)
        await pilot.press("enter")
        assert isinstance(app.screen, ContextScreen)
        await pilot.press("escape", "/")
        assert popup.display
        await pilot.press("down")
        selected = app._matches[popup.highlighted]
        await pilot.press("up", "down", "tab")
        assert editor.text == selected and not popup.display
        editor.load_text("/help")
        await pilot.press("escape", "enter")
        assert isinstance(app.screen, HelpScreen)
        app.screen.query_one("#close-help").scroll_visible(animate=False)
        await pilot.pause()
        await pilot.click("#close-help")
        editor.load_text("/zzzz")
        await pilot.press("enter")
        assert editor.text == "/zzzz" and popup.display
        await pilot.press("escape", "enter")
        assert "Unknown command" in visible(app)


@pytest.mark.asyncio
async def test_file_picker_attach_remove_snapshot_and_history(
    session, monkeypatch, tmp_path
):
    from textual.widgets import OptionList

    from sourcesift import Request

    path = tmp_path / "notes [draft].md"
    path.write_text("Before send")
    calls = []

    async def respond(request, *, on_event):
        calls.append(request)
        path.write_text("Changed after send")
        return Result(answer="Attached", model="example/test")

    monkeypatch.setattr(session, "run", respond)
    app = ChatApp(session, workspace=tmp_path)
    async with app.run_test(size=(100, 32)) as pilot:
        editor = app.query_one("#prompt", TextArea)
        await pilot.press("R", "e", "a", "d", "space", "@", "n", "o", "t")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._matches == ["notes [draft].md"]
        await pilot.press("tab")
        await pilot.pause()
        assert editor.text == 'Read @"notes [draft].md" '
        assert app._attachments == ["notes [draft].md"] and calls == []
        await pilot.click("#attachment-0")
        assert editor.text == "Read  " and app._attachments == []
        editor.move_cursor(editor.document.end)
        await pilot.press("@", "n", "o", "t", "enter")
        await pilot.pause()
        assert calls == []
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        assert len(calls) == 1 and isinstance(calls[0], Request)
        assert calls[0].context[0].text == "Before send"
        assert calls[0].context[0].name == path.name
        assert app._attachments == []
        editor.load_text("Unsent draft")
        await pilot.press("up")
        assert path.name in editor.text
        await pilot.press("down")
        assert editor.text == "Unsent draft"
        editor.load_text("user@example.org")
        editor.move_cursor(editor.document.end)
        await pilot.pause()
        assert not app.query_one("#completions", OptionList).display


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["binary", "deleted", "too_large", "too_many"])
async def test_bad_attachments_preserve_draft(session, tmp_path, failure):
    path = tmp_path / "notes.md"
    path.write_text("Notes")
    app = ChatApp(session, workspace=tmp_path)
    async with app.run_test() as pilot:
        editor = app.query_one("#prompt", TextArea)
        await pilot.press("@", "n", "o", "t")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("tab")
        draft = editor.text
        if failure == "binary":
            path.write_bytes(b"\x00")
        elif failure == "deleted":
            path.unlink()
        elif failure == "too_large":
            path.write_text("x" * (session.settings.limits.max_input_bytes + 1))
        else:
            session.settings = session.settings.model_copy(
                update={
                    "limits": session.settings.limits.model_copy(
                        update={"max_context_files": 1}
                    )
                }
            )
        await pilot.press("enter")
        assert editor.text == draft
        assert not app._turn_active and not session.turns
        assert app._attachments == ["notes.md"]


@pytest.mark.asyncio
async def test_picker_escape_does_not_cancel_turn_and_next_draft_survives(
    session, monkeypatch, tmp_path
):
    started = asyncio.Event()

    async def wait(prompt, *, on_event):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(session, "run", wait)
    app = ChatApp(session, workspace=tmp_path)
    async with app.run_test() as pilot:
        editor = app.query_one("#prompt", TextArea)
        editor.load_text("Research")
        await pilot.press("enter")
        await started.wait()
        await pilot.press("/")
        await pilot.press("escape")
        assert app._turn_active and editor.text == "/"
        await pilot.press("escape")
        await pilot.pause()
        assert not app._turn_active and editor.text == "/"


@pytest.mark.asyncio
async def test_model_onboarding_and_changes_preserve_draft():
    from textual.widgets import Input, Select

    from sourcesift.tui_panels import ModelScreen

    app = ChatApp(SourceSift(Settings()).session())
    async with app.run_test(size=(100, 40)) as pilot:
        assert isinstance(app.screen, ModelScreen)
        await pilot.pause(0.3)
        app.screen.query_one("#apply-model").scroll_visible(animate=False)
        await pilot.pause()
        await pilot.click("#apply-model")
        assert "valid provider/model" in visible(app.screen)
        app.screen.query_one("#model-name", Input).value = "example/model"
        await pilot.pause(0.3)
        app.screen.query_one("#apply-model").scroll_visible(animate=False)
        await pilot.pause()
        await pilot.click("#apply-model")
        assert "Enter an API key" in visible(app.screen)
        app.screen.query_one("#model-key", Input).value = "private-key"
        app.screen.query_one("#model-effort", Select).value = "medium"
        await pilot.pause(0.3)
        app.screen.query_one("#apply-model").scroll_visible(animate=False)
        await pilot.pause()
        await pilot.click("#apply-model")
        await pilot.pause()
        assert app.session.settings.agent.model == "example/model"
        assert app.session.settings.agent.reasoning_effort == "medium"
        assert "private-key" not in visible(app)
        editor = app.query_one("#prompt", TextArea)
        editor.load_text("Keep this draft")
        app.action_show_model()
        await pilot.pause()
        assert app.screen.query_one("#model-key", Input).value == ""
        app.screen.query_one("#model-name", Input).value = "example/other"
        await pilot.pause(0.3)
        app.screen.query_one("#apply-model").scroll_visible(animate=False)
        await pilot.pause()
        await pilot.click("#apply-model")
        await pilot.pause()
        assert editor.text == "Keep this draft"
        assert app.session.settings.agent.model == "example/other"
        assert app.session.settings.agent.api_key.get_secret_value() == "private-key"


@pytest.mark.asyncio
async def test_file_completion_in_middle_and_duplicate_basenames(
    session, monkeypatch, tmp_path
):
    from sourcesift import Request

    for name in ["one", "two"]:
        (tmp_path / name).mkdir()
        (tmp_path / name / "notes.md").write_text(name)
    captured = []

    async def run(request, settings, registry, *, state, on_event):
        captured.append(request)
        return Result(answer="Done", model="example/test")

    monkeypatch.setattr("sourcesift.core.session.run_agent", run)
    app = ChatApp(session, workspace=tmp_path)
    async with app.run_test() as pilot:
        editor = app.query_one("#prompt", TextArea)
        editor.load_text("Read @oneWRONG then compare")
        editor.move_cursor((0, 9))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("tab")
        assert editor.text == 'Read @"one/notes.md"  then compare'
        editor.move_cursor(editor.document.end)
        await pilot.press("space", "@", "t", "w", "o", "tab")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        assert len(captured) == 1 and isinstance(captured[0], Request)
        assert [(doc.name, doc.text) for doc in captured[0].context[-2:]] == [
            ("one/notes.md", "one"),
            ("two/notes.md", "two"),
        ]
        assert len(session.turns) == 1


@pytest.mark.asyncio
async def test_file_discovery_error_is_visible(session, monkeypatch, tmp_path):
    from textual.widgets import OptionList

    def fail(root):
        raise InputError("Cannot list workspace files.")

    monkeypatch.setattr("sourcesift.tui.discover_files", fail)
    app = ChatApp(session, workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("@")
        await app.workers.wait_for_complete()
        await pilot.pause()
        popup = app.query_one("#completions", OptionList)
        assert popup.display and "Cannot list" in str(popup.border_subtitle)
        await pilot.press("enter", "escape")
        assert app.query_one("#prompt", TextArea).text == "@"


@pytest.mark.asyncio
async def test_model_cancel_and_submit_reopens_setup():
    from textual.widgets import Button, Select

    from sourcesift.tui_panels import ModelScreen

    app = ChatApp(SourceSift(Settings()).session())
    async with app.run_test(size=(80, 24)) as pilot:
        button = app.screen.query_one("#apply-model", Button)
        assert button.region.bottom <= 24
        select = app.screen.query_one("#model-effort", Select)
        select.expanded = True
        await pilot.press("escape")
        assert isinstance(app.screen, ModelScreen) and not select.expanded
        await pilot.press("escape")
        app.query_one("#prompt", TextArea).load_text("Keep my prompt")
        await pilot.press("enter")
        assert isinstance(app.screen, ModelScreen)
        await pilot.press("escape")
        assert app.query_one("#prompt", TextArea).text == "Keep my prompt"
        app._turn_active = True
        app.action_show_model()
        assert "cancel the active turn" in visible(app)
