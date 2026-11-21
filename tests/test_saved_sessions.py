"""Opt-in conversation files: written only on request, private, and validated."""

import json
import os
import stat
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import format_datetime

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from textual.widgets import Markdown, Static

from sourcesift import AgentSettings, InputError, Settings, SourceSift, load_settings
from sourcesift.agents import runtime
from sourcesift.retrieval.http import Fetcher, Page
from sourcesift.tui import ChatApp


@pytest.fixture
def settings(tmp_path):
    return Settings(
        agent=AgentSettings(model="example/test", api_key="private-key"),
        sessions={"directory": tmp_path / "sessions"},
    )


@pytest.fixture
def research_model(monkeypatch):
    """First turn researches NPR; later turns answer from the retained evidence."""
    date = format_datetime(datetime.now(UTC))
    seen = []

    async def get(self, url):
        self.requests += 1
        body = f'<rss version="2.0"><channel><title>NPR</title><item><title>Library story</title><link>https://www.npr.org/library</link><description>The council approved a library.</description><pubDate>{date}</pubDate></item></channel></rss>'
        return Page(url, url, body.encode(), "application/rss+xml")

    def respond(messages, info):
        payload = next(
            json.loads(part.content)
            for message in reversed(messages)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        seen.append((payload, messages))
        tool_returned = messages[-1].parts[0].part_kind == "tool-return"
        if not payload["retained_evidence"] and not tool_returned:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "research",
                        {
                            "source_ids": ["npr"],
                            "direct_urls": [],
                            "only_sources": [],
                            "window": "recent",
                        },
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("A library was approved. [S1]")])

    @asynccontextmanager
    async def model(_settings):
        yield FunctionModel(respond)

    monkeypatch.setattr(Fetcher, "get", get)
    monkeypatch.setattr(runtime, "_openrouter_model", model)
    return seen


@pytest.mark.asyncio
async def test_nothing_is_written_unless_saving_is_requested(
    settings, research_model, tmp_path
):
    session = SourceSift(settings).session()
    await session.run("Check news")
    assert session.saved_path is None and not (tmp_path / "sessions").exists()


@pytest.mark.asyncio
async def test_save_and_continue_keep_history_evidence_and_context(
    settings, research_model, tmp_path
):
    notes = tmp_path / "notes.md"
    notes.write_text("I care about libraries.", encoding="utf-8")
    session = SourceSift(settings).session(files=[notes], save=True)
    assert session.saved_path is None
    first = await session.run("Check news")
    path = session.saved_path
    assert path is not None and path.parent == tmp_path / "sessions"
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    text = path.read_text(encoding="utf-8")
    assert "private-key" not in text
    assert "I care about libraries." in text and "The council approved" in text
    assert not list(path.parent.glob(".saving-*"))

    resumed = SourceSift(settings).session(resume=True)
    assert resumed.saved_path == path
    assert resumed.turns == session.turns and resumed.turns[0][1] == first
    assert resumed.context == session.context
    assert [item.id for item in resumed.evidence] == ["S1"]
    second = await resumed.run("Say that again")
    payload, messages = research_model[-1]
    assert payload["retained_evidence"][0]["text"] == "The council approved a library."
    assert "Check news" in str(messages)
    assert second.references[0].id == "S1" and second.http_requests == 0
    # The continued conversation keeps writing to the same file.
    assert resumed.saved_path == path and len(list(path.parent.glob("*.json"))) == 1
    assert len(json.loads(path.read_text(encoding="utf-8"))["turns"]) == 2

    # /new starts a separate file and leaves the earlier conversation in place.
    resumed.reset()
    assert resumed.saved_path is None
    await resumed.run("Check news")
    assert resumed.saved_path != path and path.exists()
    assert SourceSift(settings).session(resume=True).saved_path == resumed.saved_path


def test_continue_requires_a_readable_saved_conversation(settings, tmp_path):
    app = SourceSift(settings)
    with pytest.raises(InputError, match="no saved conversation"):
        app.session(resume=True)
    with pytest.raises(InputError, match="keeps its original context"):
        app.session(resume=True, files=[tmp_path / "notes.md"])
    folder = tmp_path / "sessions"
    folder.mkdir()
    for name, content in [
        ("a.json", "not json"),
        ("b.json", "[]"),
        ("c.json", json.dumps({"version": 2})),
        ("d.json", json.dumps({"version": 1, "messages": [{"kind": "bad"}]})),
        ("e.json", "x" * (8 * settings.limits.max_session_bytes + 1)),
    ]:
        for old in folder.glob("*.json"):
            old.unlink()
        (folder / name).write_text(content, encoding="utf-8")
        with pytest.raises(InputError, match="cannot be read"):
            app.session(resume=True)


def test_continue_ignores_links_in_the_sessions_directory(settings, tmp_path):
    folder = tmp_path / "sessions"
    folder.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (folder / "link.json").symlink_to(outside)
    with pytest.raises(InputError, match="no saved conversation"):
        SourceSift(settings).session(resume=True)


@pytest.mark.asyncio
async def test_a_failed_save_still_returns_the_turn(settings, research_model, tmp_path):
    (tmp_path / "sessions").write_text("a file blocks the directory", encoding="utf-8")
    session = SourceSift(settings).session(save=True)
    result = await session.run("Check news")
    assert result.answer and len(session.turns) == 1
    assert session.save_error is not None and "Cannot save" in session.save_error
    assert session.saved_path is None


def test_config_enables_saving_and_resolves_the_directory(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '[sessions]\nsave = true\ndirectory = "chats"\n', encoding="utf-8"
    )
    loaded = load_settings(
        config, overrides={"agent": {"model": "example/test", "api_key": "k"}}
    )
    assert loaded.sessions.save and loaded.sessions.directory == tmp_path / "chats"
    app = SourceSift(loaded)
    assert app.session()._store is not None
    assert app.session(save=False)._store is None
    assert not Settings().sessions.save


def test_chat_flags_reach_the_session(monkeypatch, settings):
    from sourcesift import cli

    calls = []

    class FakeApp:
        def __init__(self, session, *, debug):
            calls.append(session)

        def run(self):
            pass

    def session(self, **kwargs):
        calls.append(kwargs)
        return "session"

    monkeypatch.setattr("sourcesift.tui.ChatApp", FakeApp)
    monkeypatch.setattr(cli.SourceSift, "session", session)
    monkeypatch.setattr(cli, "load_settings", lambda *args, **kwargs: settings)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    for arguments, expected in [
        ([], {"files": (), "save": None, "resume": False}),
        (["--save"], {"files": (), "save": True, "resume": False}),
        (["--continue"], {"files": (), "save": None, "resume": True}),
        (["-c"], {"files": (), "save": None, "resume": True}),
    ]:
        calls.clear()
        monkeypatch.setattr(sys, "argv", ["ssift", "chat", *arguments])
        cli.main()
        assert calls == [expected, "session"]


@pytest.mark.asyncio
async def test_continued_chat_shows_earlier_turns(settings, research_model):
    session = SourceSift(settings).session(save=True)
    await session.run("Check news")
    app = ChatApp(SourceSift(settings).session(resume=True))
    async with app.run_test(size=(100, 30)):
        shown = "\n".join(str(widget.content) for widget in app.query(Static))
        assert "Check news" in shown and "Continued saved conversation" in shown
        assert "[S1] Library story" in shown
        assert len(app.query(Markdown)) == 1
