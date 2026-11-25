"""Opt-in conversation files: written only on request, private, and validated."""

import json
import os
import stat
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import format_datetime

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from sourcesift import AgentSettings, InputError, Settings, SourceSift, load_settings
from sourcesift.agents import runtime
from sourcesift.retrieval.http import Fetcher, Page


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
    assert path is not None and path.name == "conversation.json"
    assert path.parent == tmp_path / "sessions" / str(session.id)
    assert session.title == "Check news" and session.artifacts_path is not None
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.parent.parent.stat().st_mode) == 0o700
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
    # Only the latest request carries the catalog and the evidence text: the
    # earlier turn keeps its task and which evidence its tool reply found.
    earlier = str(messages[:-1])
    assert "earlier_turn" in earlier and '"catalog":' not in earlier
    assert "The council approved" not in earlier and "Library story" in earlier
    assert "feeds.npr.org" not in json.dumps(payload["catalog"])
    # The continued conversation keeps writing to the same folder.
    assert resumed.saved_path == path
    assert len(list((tmp_path / "sessions").iterdir())) == 1
    assert len(json.loads(path.read_text(encoding="utf-8"))["turns"]) == 2

    # A reset starts a separate folder and leaves the earlier conversation in place.
    resumed.reset()
    assert resumed.saved_path is None and resumed.title == ""
    await resumed.run("Other news")
    assert resumed.saved_path != path and path.exists()
    app = SourceSift(settings)
    assert app.session(resume=True).saved_path == resumed.saved_path

    # Conversations are listed newest first and reopened, renamed, or deleted by ID.
    newest, oldest = app.conversations()
    assert (newest.id, newest.title, newest.turns) == (resumed.id, "Other news", 1)
    assert (oldest.id, oldest.title, oldest.turns) == (session.id, "Check news", 2)
    reopened = app.session(resume=oldest.id)
    assert reopened.saved_path == path and len(reopened.turns) == 2
    reopened.rename("  Library   watch ")
    with pytest.raises(InputError, match="name"):
        reopened.rename("   ")
    # A new name does not move the conversation up the list.
    assert [c.title for c in app.conversations()] == ["Other news", "Library watch"]
    assert app.session(resume=oldest.id).title == "Library watch"
    kept = reopened.keep_answer(0)
    assert reopened.artifacts_path == path.parent / "artifacts"
    saved = path.parent / "artifacts" / "A1-check-news.qmd"
    assert "A library was approved. [@S1]" in saved.read_text(encoding="utf-8")
    assert reopened.save_artifacts() == [saved]
    assert app.conversations()[0].artifacts == 1 and kept.id == "A1"
    app.delete_conversation(oldest.id)
    assert [c.id for c in app.conversations()] == [newest.id]
    assert not path.parent.exists()
    for missing in (oldest.id, "../outside", "20260101-000000-zzzzzzzz"):
        with pytest.raises(InputError, match="no such saved conversation"):
            app.delete_conversation(missing)
        with pytest.raises(InputError, match="no such saved conversation"):
            app.session(resume=missing)


def test_continue_requires_a_readable_saved_conversation(settings, tmp_path):
    app = SourceSift(settings)
    with pytest.raises(InputError, match="no saved conversation"):
        app.session(resume=True)
    with pytest.raises(InputError, match="keeps its original context"):
        app.session(resume=True, files=[tmp_path / "notes.md"])
    folder = tmp_path / "sessions" / "20260102-030405-0a1b2c3d"
    folder.mkdir(parents=True)
    meta = {
        "id": folder.name,
        "title": "Old",
        "updated_at": "2026-01-02T03:04:05Z",
        "turns": 1,
    }
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for content in [
        "not json",
        "[]",
        json.dumps({"version": 1}),
        json.dumps({"version": 2, "messages": [{"kind": "bad"}]}),
        "x" * (8 * settings.limits.max_session_bytes + 1),
    ]:
        (folder / "conversation.json").write_text(content, encoding="utf-8")
        with pytest.raises(InputError, match="cannot be read"):
            app.session(resume=True)
    # A conversation whose listing entry is unreadable is left out of the list.
    (folder / "meta.json").write_text("{}", encoding="utf-8")
    assert app.conversations() == []
    # Files from the earlier one-file-per-conversation layout are not conversations.
    (tmp_path / "sessions" / "20250101-000000-0a1b2c3d.json").write_text("{}")
    assert app.conversations() == []


def test_continue_ignores_links_in_the_sessions_directory(settings, tmp_path):
    folder = tmp_path / "sessions"
    folder.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "meta.json").write_text("{}", encoding="utf-8")
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    (folder / "20260102-030405-0a1b2c3d").symlink_to(outside)
    app = SourceSift(settings)
    with pytest.raises(InputError, match="no saved conversation"):
        app.session(resume=True)
    with pytest.raises(InputError, match="cannot be read"):
        app.session(resume="20260102-030405-0a1b2c3d")
    with pytest.raises(InputError, match="no such saved conversation"):
        app.delete_conversation("20260102-030405-0a1b2c3d")
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


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
