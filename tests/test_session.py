"""Multi-turn evidence, rollback, budgets, and streaming through the real agent."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import format_datetime

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from sourcesift import (
    AgentSettings,
    ContextSettings,
    InputError,
    Limits,
    ModelError,
    Settings,
    SourceSift,
    load_settings,
)
from sourcesift.agents import runtime
from sourcesift.retrieval.http import Fetcher, Page


@pytest.fixture
def settings():
    return Settings(agent=AgentSettings(model="example/test", api_key="private-key"))


@pytest.fixture
def install(monkeypatch):
    def install_model(respond=None, stream=None):
        @asynccontextmanager
        async def model(settings):
            if stream is not None:
                yield FunctionModel(stream_function=stream)
            else:
                assert respond is not None
                yield FunctionModel(respond)

        monkeypatch.setattr(runtime, "_openrouter_model", model)

    return install_model


def task_payload(messages):
    return next(
        json.loads(part.content)
        for message in reversed(messages)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    )


@pytest.mark.asyncio
async def test_followups_retain_evidence_and_upgrade_second_article(
    settings, install, monkeypatch
):
    calls = 0

    async def get(self, url):
        self.requests += 1
        date = format_datetime(datetime.now(UTC))
        if "feeds.npr" in url:
            body = f'<rss version="2.0"><channel><title>NPR</title><item><title>First story</title><link>https://www.npr.org/first</link><description>First summary.</description><pubDate>{date}</pubDate></item><item><title>Second story</title><link>https://www.npr.org/second</link><description>Second summary.</description><pubDate>{date}</pubDate></item></channel></rss>'
        else:
            assert url == "https://www.npr.org/second"
            body = (
                "<html><head><title>Second story</title></head><body><article><h1>Second story</h1><p>"
                + "The second story explains the public library funding proposal in detail. "
                * 30
                + "</p></article></body></html>"
            )
        return Page(
            url,
            url,
            body.encode(),
            "application/rss+xml" if "feeds.npr" in url else "text/html",
        )

    monkeypatch.setattr(Fetcher, "get", get)

    async def respond(messages, info):
        nonlocal calls
        calls += 1
        payload = task_payload(messages)
        if calls == 1:
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
        if calls == 2:
            return ModelResponse(
                parts=[TextPart("1. First story [S1]\n2. Second story [S2]")]
            )
        assert payload["retained_evidence"][1]["id"] == "S2"
        if calls == 3:
            assert "Second story [S2]" in str(messages)
            return ModelResponse(
                parts=[
                    ToolCallPart("read_article", {"url": "https://www.npr.org/second"})
                ]
            )
        return ModelResponse(
            parts=[TextPart("The second story describes library funding. [S2]")]
        )

    install(respond)
    session = SourceSift(settings).session()
    first = await session.run("Check news")
    second = await session.run("Read the second one")
    third = await session.run("Summarize that again")
    assert [ref.id for ref in first.references] == ["S1", "S2"]
    assert second.references[0].kind == "article"
    assert second.references[0].id == third.references[0].id == "S2"
    assert first.references[1].kind == "feed_summary"
    assert second.http_requests == 1 and third.http_requests == 0
    assert any("retained" in note for note in third.limitations)
    assert len(session.turns) == 3


@pytest.mark.asyncio
async def test_context_snapshot_reset_and_isolated_sessions(
    settings, install, tmp_path
):
    profile = tmp_path / "context.md"
    profile.write_text("My project is a library. Keep responses short.")
    config = tmp_path / "config.toml"
    config.write_text('[context]\ninstructions_file = "context.md"')
    loaded = load_settings(
        config, overrides={"agent": {"model": "example/test", "api_key": "private-key"}}
    )
    assert loaded.context.instructions_file == profile
    app = SourceSift(loaded)
    session = app.session()

    def respond(messages, info):
        assert "private-key" not in str(messages)
        assert "guidance" in str(messages)
        return ModelResponse(parts=[TextPart("Library summary")])

    install(respond)
    await session.run("What is my project?")
    profile.write_text("My project is now a park.")
    await session.run("Shorter please")
    assert "library" in session.context[0].text
    other = app.session()
    assert other.turns == () and "park" in other.context[0].text
    profile.unlink()
    with pytest.raises(InputError):
        session.reset()
    assert len(session.turns) == 2
    profile.write_text("New context")
    session.reset()
    assert len(session.turns) == 0
    assert session.context[0].text == "New context"


@pytest.mark.asyncio
async def test_failure_cancel_concurrency_and_recovery(settings, install):
    session = SourceSift(settings).session()
    install(lambda messages, info: ModelResponse(parts=[TextPart("Completed")]))
    await session.run("First")
    started = asyncio.Event()

    async def block(messages, info):
        started.set()
        await asyncio.Event().wait()

    install(block)
    task = asyncio.create_task(session.run("Cancelled prompt"))
    await started.wait()
    with pytest.raises(InputError, match="already running"):
        await session.run("Concurrent")
    with pytest.raises(InputError, match="Cancel"):
        session.reset()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not session.busy and len(session.turns) == 1

    def fail(messages, info):
        raise ModelHTTPError(503, "example/test", {"secret": "private-key"})

    install(fail)
    with pytest.raises(ModelError):
        await session.run("Failed prompt")

    def recover(messages, info):
        assert "Cancelled prompt" not in str(messages) and "Failed prompt" not in str(
            messages
        )
        assert "Completed" in str(messages)
        return ModelResponse(parts=[TextPart("Recovered")])

    install(recover)
    await session.run("Continue")
    assert len(session.turns) == 2
    with pytest.raises(InputError, match="nonempty"):
        await session.run(" ")
    assert not session.busy


@pytest.mark.asyncio
async def test_turn_and_byte_limits(settings, install):
    install(lambda messages, info: ModelResponse(parts=[TextPart("Answer")]))
    session = SourceSift(
        settings.model_copy(update={"limits": Limits(max_session_turns=1)})
    ).session()
    await session.run("first")
    with pytest.raises(InputError, match="turn limit"):
        await session.run("second")
    session.reset()
    await session.run("fresh")
    small = SourceSift(
        settings.model_copy(update={"limits": Limits(max_session_bytes=1024)})
    ).session()
    with pytest.raises(InputError, match="context limit"):
        await small.run("too large")
    assert not small.turns
    # Oversized response rolls back even when the input fit.
    install(lambda messages, info: ModelResponse(parts=[TextPart("x" * 20000)]))
    bounded = SourceSift(
        settings.model_copy(update={"limits": Limits(max_session_bytes=12000)})
    ).session()
    with pytest.raises(InputError, match="context limit"):
        await bounded.run("small")
    assert not bounded.turns


@pytest.mark.asyncio
async def test_streamed_drafts_repaired_and_tool_progress(settings, install):
    calls = 0

    async def stream(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield {
                0: DeltaToolCall(
                    name="research",
                    json_args=json.dumps(
                        {
                            "source_ids": [],
                            "direct_urls": [],
                            "only_sources": ["Unknown publication"],
                        }
                    ),
                    tool_call_id="call-1",
                )
            }
        elif calls == 2:
            yield "Unsupported [S999]"
        else:
            yield "No evidence "
            yield "available."

    install(stream=stream)
    events = []
    session = SourceSift(settings).session()
    result = await session.run("Check unknown publication", on_event=events.append)
    assert any(e.kind == "draft" and "S999" in e.text for e in events)
    assert sum(e.kind == "reset" for e in events) >= 3
    assert any("Running research" in e.text for e in events)
    assert any("Reviewing" in e.text for e in events)
    assert "could not retrieve" in result.answer
    assert "S999" not in session.turns[0][1].answer


@pytest.mark.asyncio
async def test_session_files_and_request_context(settings, install, tmp_path):
    from sourcesift import ContextDocument, Request

    path = tmp_path / "notes.md"
    path.write_text("My supplied notes")
    app = SourceSift(
        settings.model_copy(update={"context": ContextSettings(files=(path,))})
    )
    session = app.session(files=[path])

    def respond(messages, info):
        assert "Supplied inline" in str(messages)
        assert "My supplied notes" in str(messages)
        return ModelResponse(parts=[TextPart("Document analysis")])

    install(respond)
    await session.run(
        Request(
            prompt="summarize",
            context=(ContextDocument(name="inline", text="Supplied inline"),),
        ),
        files=[path],
    )
    assert len(session.context) == 2
