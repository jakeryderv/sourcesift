"""Shared async application with a synchronous convenience method."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from pydantic import ValidationError

from sourcesift.agents.runtime import run_agent, validate_model_access
from sourcesift.builtin import BUILTIN_CATALOG, builtin_toolkit
from sourcesift.core.config import Settings, load_settings
from sourcesift.core.context import prepare_request
from sourcesift.core.session import Session
from sourcesift.data import Block, Chart, StatView, TableView
from sourcesift.errors import ConfigurationError, InputError
from sourcesift.extend import DataSource, FetchContext, Toolkit, Widget
from sourcesift.models import Request, Result
from sourcesift.retrieval.http import Fetcher
from sourcesift.retrieval.research import make_window
from sourcesift.retrieval.urls import RetrievalError
from sourcesift.sources import Source, SourceRegistry


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

        self.toolkit = builtin_toolkit()
        if any("query" in s.capabilities for s in self.settings.sources.custom):
            raise ConfigurationError(
                "A live data source is defined in Python, not in configuration."
            )
        catalog = SourceRegistry((*BUILTIN_CATALOG, *self.settings.sources.custom))
        disabled = set(self.settings.sources.disabled)
        if disabled - {source.id for source in catalog.list()}:
            raise ConfigurationError("Disabled source IDs must exist in the catalog.")
        self.registry = SourceRegistry(
            source for source in catalog.list() if source.id not in disabled
        )

    def register_source(self, source: Source) -> None:
        """Add a definition for future runs; duplicate identities are rejected.

        Call before starting requests. Each run snapshots the immutable registry.
        A live data source is registered with ``register`` instead.
        """
        if "query" in source.capabilities:
            raise ConfigurationError("Register a live data source with register().")
        self.registry = SourceRegistry((*self.registry.list(), source))

    def register(self, item: DataSource | Widget) -> None:
        """Add a data source or widget defined with ``sourcesift.extend``.

        Call before starting requests. This interface is new and may change.
        Extensions are trusted Python running in this process.
        """
        sources = list(self.toolkit.sources.values())
        widgets = list(self.toolkit.widgets.values())
        if isinstance(item, DataSource):
            registry = SourceRegistry((*self.registry.list(), item.source))
            self.toolkit = Toolkit([*sources, item], widgets)
            self.registry = registry
        else:
            self.toolkit = Toolkit(sources, [*widgets, item])

    def session(
        self,
        *,
        files: Sequence[str | Path] = (),
        save: bool | None = None,
        resume: bool = False,
    ) -> Session:
        """Create an independent conversation with snapshotted context.

        It stays in memory unless ``save`` is true or ``[sessions].save`` is set.
        ``resume`` continues the most recently saved conversation.
        """
        return Session(
            self.settings,
            self.registry,
            toolkit=self.toolkit,
            files=files,
            save=self.settings.sessions.save if save is None else save,
            resume=resume,
        )

    async def refresh(self, block: Block) -> Block:
        """Fetch a visual's data again and redraw it, without a model request.

        The source and widget run with the parameters and options recorded in the
        block, through the same bounded fetcher. The caller decides how often;
        ``block.refresh_seconds`` is the source's own minimum interval.
        """
        data_source = self.toolkit.sources.get(block.source_id)
        chosen = self.toolkit.widgets.get(block.widget)
        if (
            data_source is None
            or chosen is None
            or self.registry.resolve(block.source_id) is None
        ):
            raise InputError("This visual's source or widget is not available.")
        try:
            params = data_source.params.model_validate(block.params)
            options = chosen.options.model_validate(block.options)
        except ValidationError:
            raise InputError("This visual's parameters are no longer valid.") from None
        now = datetime.now(UTC)
        window = make_window(block.window, self.settings, now)
        limit = self.settings.limits.max_items_per_source
        try:
            async with Fetcher(self.settings.limits) as fetcher:
                result = await data_source.fetch(
                    params, FetchContext(fetcher.get, now, window.start, limit)
                )
            shape = next(
                s
                for s in result.data
                if isinstance(s, data_source.returns) and isinstance(s, chosen.accepts)
            )
            view = chosen.render(shape, options)
            if not isinstance(view, Chart | TableView | StatView):
                raise TypeError
        except RetrievalError as exc:
            raise InputError(f"Could not refresh: {exc}") from None
        except (ArithmeticError, LookupError, StopIteration, TypeError, ValueError):
            raise InputError(
                "The source returned nothing this visual can draw."
            ) from None
        return block.model_copy(update={"view": view})

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
        return await run_agent(
            prepared, self.settings, self.registry, toolkit=self.toolkit
        )

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
