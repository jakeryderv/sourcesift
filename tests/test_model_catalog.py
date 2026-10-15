"""Public model catalog parsing, bounded transport, and per-chat caching."""

import asyncio
import json

import httpx
import pytest

from sourcesift import ConfigurationError
from sourcesift.model_catalog import CatalogModel, ModelCatalog, parse_catalog


def record(identifier="example/research", name="Research Model", **changes):
    return {
        "id": identifier,
        "name": name,
        "supported_parameters": ["tools", "reasoning"],
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        **changes,
    }


def test_catalog_filters_models_and_malformed_rows():
    rows = [
        record(),
        record(),
        record("other/model", None),
        None,
        record("bad id/model"),
        record("invalid"),
        record("bad/\x1b"),
        record(supported_parameters=[]),
        record(supported_parameters="tools"),
        record(architecture={"output_modalities": ["image"]}),
        record(architecture=None),
        record(architecture={"output_modalities": "text"}),
    ]
    models = parse_catalog(json.dumps({"data": rows}).encode())
    assert models == (
        CatalogModel("example/research", "Research Model"),
        CatalogModel("other/model", "other/model"),
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"invalid",
        b"\xff",
        b"[]",
        b"{}",
        b'{"data": null}',
        b'{"data": []}',
        json.dumps({"data": [None] * 10001}).encode(),
    ],
)
def test_invalid_catalog_has_safe_error(payload):
    with pytest.raises(ConfigurationError, match="Enter a provider/model ID manually"):
        parse_catalog(payload)


@pytest.mark.asyncio
async def test_catalog_loads_without_credentials_and_caches():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [record()]})

    catalog = ModelCatalog(transport=httpx.MockTransport(respond))
    first = await catalog.load()
    assert first == await catalog.load()
    assert len(requests) == 1
    assert str(requests[0].url) == "https://openrouter.ai/api/v1/models"
    assert "authorization" not in requests[0].headers
    assert requests[0].content == b""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["http", "redirect", "timeout", "oversized", "invalid"]
)
async def test_catalog_failure_is_safe_and_retried_on_reopen(failure, monkeypatch):
    attempts = []

    def respond(request):
        attempts.append(request)
        if len(attempts) > 1:
            return httpx.Response(200, json={"data": [record()]})
        if failure == "http":
            return httpx.Response(500, text="private provider body")
        if failure == "redirect":
            return httpx.Response(
                302, headers={"location": "https://elsewhere.example"}
            )
        if failure == "timeout":
            raise httpx.ReadTimeout("private provider body")
        if failure == "oversized":
            return httpx.Response(200, content=b" " * 5000)
        return httpx.Response(200, content=b"private provider body")

    monkeypatch.setattr("sourcesift.model_catalog.MAX_CATALOG_BYTES", 4096)
    catalog = ModelCatalog(transport=httpx.MockTransport(respond))
    with pytest.raises(ConfigurationError) as exc:
        await catalog.load()
    assert "private" not in str(exc.value)
    assert len(await catalog.load()) == 1
    assert len(attempts) == 2


@pytest.mark.asyncio
async def test_catalog_total_timeout_and_cancellation(monkeypatch):
    async def wait(request):
        await asyncio.Event().wait()

    catalog = ModelCatalog(transport=httpx.MockTransport(wait))
    monkeypatch.setattr("sourcesift.model_catalog.CATALOG_TIMEOUT", 0.01)
    with pytest.raises(ConfigurationError, match="unavailable"):
        await catalog.load()
    task = asyncio.create_task(catalog.load())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
