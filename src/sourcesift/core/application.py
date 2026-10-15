"""Shared async application with a synchronous convenience method."""

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO

from pydantic import ValidationError

from sourcesift.agents.runtime import run_agent, validate_model_access
from sourcesift.core.config import Settings, load_settings
from sourcesift.core.context import prepare_request
from sourcesift.errors import ConfigurationError, InputError
from sourcesift.models import Request, Result
from sourcesift.sources import BUILTIN_SOURCES, Source, SourceRegistry


class SourceSift:
    """Run independent requests through the shared application.

    Args:
        settings: Explicit resolved settings; bypasses file/environment loading.
        config_path: Optional TOML path when settings are not supplied.
        model: Explicit OpenRouter model ID overriding config/environment values.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        config_path: str | Path | None = None,
        model: str | None = None,
    ) -> None:
        if settings is not None and (config_path is not None or model is not None):
            raise ConfigurationError(
                "Pass resolved settings or config/model overrides, not both."
            )
        self.settings = (
            settings
            if settings is not None
            else load_settings(
                config_path,
                overrides={"agent": {"model": model}} if model is not None else None,
            )
        )

        catalog = SourceRegistry((*BUILTIN_SOURCES, *self.settings.sources.custom))
        disabled = set(self.settings.sources.disabled)
        if disabled - {source.id for source in catalog.list()}:
            raise ConfigurationError("Disabled source IDs must exist in the catalog.")
        self.registry = SourceRegistry(
            source for source in catalog.list() if source.id not in disabled
        )

    def register_source(self, source: Source) -> None:
        """Add a definition for future runs; duplicate identities are rejected.

        Call before starting requests. Each run snapshots the immutable registry.
        Third-party executable plugins are a later capability.
        """
        self.registry = SourceRegistry((*self.registry.list(), source))

    async def run(
        self,
        request: str | Request,
        *,
        files: Sequence[str | Path] = (),
        stdin: BinaryIO | None = None,
    ) -> Result:
        """Run one request with optional files and an explicitly supplied input stream.

        No previous run's context or conversation is retained. The SDK never reads
        process stdin implicitly. Use Request for labeled context or plain output.
        """
        try:
            parsed = Request(prompt=request) if isinstance(request, str) else request
        except ValidationError:
            raise InputError("Provide a nonempty prompt.") from None
        validate_model_access(self.settings)
        prepared = prepare_request(parsed, self.settings, files=files, stdin=stdin)
        return await run_agent(prepared, self.settings, self.registry)

    def run_sync(
        self,
        request: str | Request,
        *,
        files: Sequence[str | Path] = (),
        stdin: BinaryIO | None = None,
    ) -> Result:
        """Run from an ordinary script; use await run() inside an active event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise InputError(
                "run_sync() cannot run inside an event loop; use await app.run(...)."
            )
        return asyncio.run(self.run(request, files=files, stdin=stdin))
