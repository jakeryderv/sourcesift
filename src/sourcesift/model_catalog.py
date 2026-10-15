"""Public OpenRouter model discovery for the interactive setup panel."""

import asyncio
import json
from dataclasses import dataclass

import httpx

from sourcesift.errors import ConfigurationError

CATALOG_URL = "https://openrouter.ai/api/v1/models"
MAX_CATALOG_BYTES = 4 * 1024 * 1024
CATALOG_TIMEOUT = 8
CATALOG_UNAVAILABLE = "Model catalog unavailable. Enter a provider/model ID manually."


@dataclass(frozen=True)
class CatalogModel:
    id: str
    name: str


def parse_catalog(payload: bytes) -> tuple[CatalogModel, ...]:
    """Keep valid text-output models advertising tool support; ignore other rows."""
    try:
        data = json.loads(payload)
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise TypeError
        if len(data["data"]) > 10000:
            raise ValueError
        models = {}
        for row in data["data"]:
            if not isinstance(row, dict):
                continue
            identifier, name = row.get("id"), row.get("name")
            parameters, architecture = (
                row.get("supported_parameters"),
                row.get("architecture"),
            )
            if (
                not isinstance(identifier, str)
                or not 1 < len(identifier) <= 256
                or "/" not in identifier
                or not identifier.isprintable()
                or any(c.isspace() for c in identifier)
                or not isinstance(parameters, list)
                or "tools" not in parameters
                or not isinstance(architecture, dict)
                or not isinstance(architecture.get("input_modalities"), list)
                or "text" not in architecture["input_modalities"]
                or not isinstance(architecture.get("output_modalities"), list)
                or "text" not in architecture["output_modalities"]
            ):
                continue
            if not isinstance(name, str) or not name.isprintable() or len(name) > 256:
                name = identifier
            models[identifier] = CatalogModel(identifier, name)
        if not models:
            raise ValueError
        return tuple(models[key] for key in sorted(models))
    except (TypeError, ValueError, RecursionError):
        raise ConfigurationError(CATALOG_UNAVAILABLE) from None


class ModelCatalog:
    """Cache a successful public catalog for one chat, with no credentials or prompts."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._models: tuple[CatalogModel, ...] | None = None

    async def load(self) -> tuple[CatalogModel, ...]:
        if self._models is not None:
            return self._models
        try:
            async with asyncio.timeout(CATALOG_TIMEOUT):
                async with (
                    httpx.AsyncClient(
                        transport=self._transport, timeout=5, follow_redirects=False
                    ) as client,
                    client.stream("GET", CATALOG_URL) as response,
                ):
                    response.raise_for_status()
                    payload = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        payload.extend(chunk)
                        if len(payload) > MAX_CATALOG_BYTES:
                            raise ValueError
                    models = parse_catalog(bytes(payload))
        except (httpx.HTTPError, TimeoutError, ValueError):
            raise ConfigurationError(CATALOG_UNAVAILABLE) from None
        self._models = models
        return models
