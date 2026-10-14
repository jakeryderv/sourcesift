"""SDK execution uses the real agent loop with deterministic substitute models."""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from pydantic_ai import models
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from sourcesift import (
    AgentSettings,
    ConfigurationError,
    InputError,
    Limits,
    ModelError,
    Request,
    Settings,
    SourceSift,
)
from sourcesift.agents import runtime


@pytest.fixture(autouse=True)
def disallow_live_models(monkeypatch):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


@pytest.fixture
def settings():
    return Settings(agent=AgentSettings(model="example/test", api_key="private-key"))


@pytest.fixture
def install_model(monkeypatch):
    def install(function):
        @asynccontextmanager
        async def model(_settings):
            yield FunctionModel(function)

        monkeypatch.setattr(runtime, "_openrouter_model", model)

    return install


def test_sync_async_context_and_usage(settings, install_model, tmp_path):
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        return ModelResponse(parts=[TextPart("Document summary")])

    install_model(respond)
    path = tmp_path / "report.md"
    path.write_text("Document contents", encoding="utf-8")
    app = SourceSift(settings)
    first = app.run_sync("summarize", files=[path])
    second = asyncio.run(app.run("summarize", files=[path]))
    assert first.answer == second.answer == "Document summary"
    assert first.usage.requests == 1
    assert first.usage.input_tokens > 0
    assert first.limitations == (runtime.NO_RETRIEVAL,)
    for messages, info in calls:
        prompts = [
            part.content
            for msg in messages
            if isinstance(msg, ModelRequest)
            for part in msg.parts
            if isinstance(part, UserPromptPart)
        ]
        assert len(prompts) == 1
        payload = json.loads(prompts[0])
        assert payload["task"] == "summarize"
        assert payload["context"][0]["text"] == "Document contents"
        assert "private-key" not in str(messages)
        assert "no retrieval" in info.instructions
        assert not info.function_tools


def test_fresh_requests_and_plain_format(settings, install_model):
    seen = []

    def respond(messages, info):
        seen.append(messages)
        return ModelResponse(parts=[TextPart("answer")])

    install_model(respond)
    app = SourceSift(settings)
    app.run_sync(Request(prompt="first", output_format="plain"))
    app.run_sync("second")
    assert '"output_format": "plain"' in str(seen[0])
    assert "first" not in str(seen[1])


@pytest.mark.asyncio
async def test_sync_in_event_loop_and_cancellation(settings, install_model):
    with pytest.raises(InputError, match="await app.run"):
        SourceSift(settings).run_sync("task")
    started = asyncio.Event()

    async def respond(messages, info):
        started.set()
        await asyncio.Event().wait()
        return ModelResponse(parts=[TextPart("unreachable")])

    install_model(respond)
    task = asyncio.create_task(SourceSift(settings).run("task"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_timeout(settings, install_model):
    async def respond(messages, info):
        await asyncio.Event().wait()
        return ModelResponse(parts=[TextPart("unreachable")])

    install_model(respond)
    app = SourceSift(
        Settings(agent=settings.agent, limits=Limits(timeout_seconds=0.01))
    )
    with pytest.raises(ModelError, match="timed out"):
        app.run_sync("task")


@pytest.mark.parametrize(
    "status, message",
    [
        (401, "rejected access"),
        (402, "credits"),
        (429, "rate limit"),
        (503, "service availability"),
    ],
)
def test_provider_errors_are_sanitized(settings, install_model, status, message):
    count = 0

    def respond(messages, info):
        nonlocal count
        count += 1
        raise ModelHTTPError(
            status, "example/test", {"error": "private-key document contents"}
        )

    install_model(respond)
    with pytest.raises(ModelError, match=message) as exc:
        SourceSift(settings).run_sync("task")
    assert "private-key" not in str(exc.value)
    assert "document contents" not in str(exc.value)
    assert count == 1


def test_missing_configuration_and_invalid_request(settings):
    with pytest.raises(ConfigurationError, match="Select"):
        SourceSift(Settings()).run_sync("task")
    with pytest.raises(ConfigurationError, match="OPENROUTER_API_KEY"):
        SourceSift(Settings(agent=AgentSettings(model="example/test"))).run_sync("task")
    with pytest.raises(ConfigurationError, match="not both"):
        SourceSift(settings, model="example/other")
    with pytest.raises(InputError, match="nonempty"):
        SourceSift(settings).run_sync("  ")


def test_empty_answer(settings, install_model):
    install_model(lambda messages, info: ModelResponse(parts=[TextPart("   ")]))
    with pytest.raises(ModelError, match="empty answer"):
        SourceSift(settings).run_sync("task")


@pytest.mark.parametrize("status", [200, 401, 429, 503])
def test_openrouter_transport_contract(monkeypatch, status):
    import httpx2
    from openai import AsyncOpenAI

    requests = []
    clients = []

    def handle(request):
        requests.append(request)
        if status != 200:
            return httpx2.Response(
                status, json={"error": {"message": "private-key", "code": status}}
            )
        return httpx2.Response(
            200,
            json={
                "id": "test-completion",
                "object": "chat.completion",
                "provider": "OpenAI",
                "created": 1,
                "model": "openai/gpt-6.1-sol",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "A summary."},
                    }
                ],
                "usage": {
                    "prompt_tokens": 30,
                    "completion_tokens": 10,
                    "total_tokens": 40,
                },
            },
        )

    def client(**kwargs):
        assert kwargs["max_retries"] == 0
        instance = AsyncOpenAI(
            **kwargs,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
        )
        clients.append(instance)
        return instance

    monkeypatch.setattr(runtime, "AsyncOpenAI", client)
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    settings = Settings(
        agent=AgentSettings(
            model="openai/gpt-6.1-sol", api_key="private-key", reasoning_effort="medium"
        )
    )
    if status == 200:
        result = SourceSift(settings).run_sync("Summarize")
        assert result.answer == "A summary."
        assert result.usage.input_tokens == 30
        assert result.usage.output_tokens == 10
    else:
        with pytest.raises(ModelError) as exc:
            SourceSift(settings).run_sync("Summarize")
        assert "private-key" not in str(exc.value)
    assert len(requests) == 1
    assert str(requests[0].url) == "https://openrouter.ai/api/v1/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "openai/gpt-6.1-sol"
    assert payload["reasoning"] == {"effort": "medium", "exclude": True}
    assert payload["max_tokens"] == 2048
    assert all(c.is_closed() for c in clients)


def test_truncated_answer_is_disclosed(settings, install_model):
    install_model(
        lambda messages, info: ModelResponse(
            parts=[TextPart("Partial answer")], finish_reason="length"
        )
    )
    result = SourceSift(settings).run_sync("task")
    assert any("incomplete" in limitation for limitation in result.limitations)
