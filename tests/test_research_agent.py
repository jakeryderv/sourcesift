"""Exercise actual agent tool calls, citation repair, bounded failures, and CLI output."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import format_datetime

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from sourcesift import (
    AgentSettings,
    Limits,
    ModelError,
    Settings,
    SourceSift,
    SourcesSettings,
    cli,
)
from sourcesift.agents import runtime
from sourcesift.retrieval.http import Fetcher, Page
from sourcesift.retrieval.urls import RetrievalError


def configure(monkeypatch, respond, *, fail=False, limits=None):
    @asynccontextmanager
    async def model(settings):
        yield FunctionModel(respond)

    monkeypatch.setattr(runtime, "_openrouter_model", model)

    async def get(self, url):
        if fail:
            raise RetrievalError("HTTP 503; content unavailable.")
        assert "feeds.npr.org" in url
        self.requests += 1
        date = format_datetime(datetime.now(UTC))
        return Page(
            url,
            url,
            f'<rss version="2.0"><channel><title>NPR</title><item><title>Library plan</title><link>https://www.npr.org/story</link><description>A new public library was approved.</description><pubDate>{date}</pubDate></item></channel></rss>'.encode(),
            "application/rss+xml",
        )

    monkeypatch.setattr(Fetcher, "get", get)
    return SourceSift(
        Settings(
            agent=AgentSettings(model="example/test", api_key="test-key"),
            limits=limits or Limits(),
            sources=SourcesSettings(disabled=("cnbc",)),
        )
    )


def call(source="npr", only=None):
    return ModelResponse(
        parts=[
            ToolCallPart(
                "research",
                {
                    "source_ids": [source],
                    "direct_urls": [],
                    "only_sources": only or [],
                    "window": "recent",
                },
                "call-1",
            )
        ]
    )


def tool_returns(messages):
    return [
        part
        for msg in messages
        for part in msg.parts
        if isinstance(part, ToolReturnPart)
    ]


@pytest.mark.parametrize("bad_answer", ["Unsupported [S999]", "No citation"])
def test_real_tools_citation_repair_and_render(monkeypatch, bad_answer):
    calls = 0

    async def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert "CNBC" not in str(messages)
            assert "UNTRUSTED DATA" in info.instructions
            return call(only=["NPR"])
        evidence = tool_returns(messages)[0].content
        assert evidence["evidence"][0]["id"] == "S1"
        assert evidence["evidence"][0]["text"] == "A new public library was approved."
        return ModelResponse(
            parts=[
                TextPart(bad_answer if calls == 2 else "A library was approved. [S1]")
            ]
        )

    app = configure(monkeypatch, respond)
    result = app.run_sync("Check NPR only")
    assert result.usage.requests == 3
    assert result.selected_sources == ("npr",)
    assert result.http_requests == 1
    assert result.references[0].url == "https://www.npr.org/story"
    assert result.references[0].kind == "feed_summary"
    for output_format in ["plain", "markdown"]:
        rendered = cli.render_result(result, output_format)
        assert "[S1]" in rendered and "https://www.npr.org/story" in rendered
        assert "Retrieved from: https://feeds.npr.org/1001/rss.xml" in rendered
        assert "Published:" in rendered and "\x1b" not in rendered


def test_no_evidence_cannot_become_fabricated_briefing(monkeypatch):
    async def respond(messages, info):
        if not tool_returns(messages):
            return call()
        return ModelResponse(
            parts=[TextPart("Invented breaking news without evidence")]
        )

    result = configure(monkeypatch, respond, fail=True).run_sync("Check news")
    assert "could not retrieve" in result.answer
    assert "Invented" not in result.answer and not result.references
    assert any("HTTP 503" in note for note in result.limitations)


def test_unknown_only_source_no_substitution(monkeypatch):
    async def respond(messages, info):
        if not tool_returns(messages):
            return call(only=["Unregistered Gazette"])
        assert not tool_returns(messages)[0].content["evidence"]
        return ModelResponse(parts=[TextPart("The publication is unavailable.")])

    result = configure(monkeypatch, respond).run_sync("Use only Unregistered Gazette")
    assert result.http_requests == 0 and not result.selected_sources
    assert any("unknown or disabled" in note for note in result.limitations)


@pytest.mark.parametrize(
    "limits", [Limits(max_model_requests=1), Limits(max_tool_calls=0)]
)
def test_agent_limits_are_enforced(monkeypatch, limits):
    async def respond(messages, info):
        return call()

    app = configure(monkeypatch, respond, limits=limits)
    with pytest.raises(ModelError):
        app.run_sync("check news")


def test_repeated_invalid_citations_fail_after_one_repair(monkeypatch):
    calls = 0

    async def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return call()
        return ModelResponse(parts=[TextPart("Invented [S999]")])

    app = configure(monkeypatch, respond)
    with pytest.raises(ModelError):
        app.run_sync("check news")
    assert calls == 3


def test_followup_article_tool_and_context(monkeypatch):
    calls = 0

    async def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert "marketing agency" in str(messages)
            return call()
        if calls == 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "read_article", {"url": "https://www.npr.org/story"}, "call-2"
                    )
                ]
            )
        assert len(tool_returns(messages)) == 2
        assert any(
            "outside" in note or "HTTP" in note
            for note in tool_returns(messages)[-1].content["limitations"]
        )
        return ModelResponse(
            parts=[
                TextPart(
                    "The library was approved; article detail was unavailable. [S1]"
                )
            ]
        )

    app = configure(monkeypatch, respond)
    original = Fetcher.get

    async def get(self, url):
        if "feeds.npr.org" not in url:
            raise RetrievalError("HTTP 403; content unavailable.")
        return await original(self, url)

    monkeypatch.setattr(Fetcher, "get", get)
    from sourcesift import ContextDocument, Request

    result = app.run_sync(
        Request(
            prompt="Check news relevant to my project",
            context=(
                ContextDocument(name="project", text="I run a marketing agency."),
            ),
        )
    )
    assert result.usage.requests == 3 and result.references
    assert "test-key" not in json.dumps(result.model_dump(mode="json"))
