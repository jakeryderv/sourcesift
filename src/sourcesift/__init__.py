"""SourceSift: a Python SDK for requests with explicit document context."""

from sourcesift.core.application import SourceSift
from sourcesift.core.config import (
    AgentSettings,
    ContextSettings,
    Limits,
    ReportsSettings,
    SessionsSettings,
    Settings,
    SourcesSettings,
    load_settings,
)
from sourcesift.core.session import Session
from sourcesift.data import (
    Block,
    Column,
    Figure,
    Stat,
    StatView,
    Table,
    TableView,
)
from sourcesift.errors import (
    ConfigurationError,
    InputError,
    ModelError,
    SourceSiftError,
)
from sourcesift.extend import (
    DataSource,
    FetchContext,
    Record,
    SourceResult,
    Widget,
    source,
    widget,
)
from sourcesift.models import (
    ContextDocument,
    Reference,
    Request,
    ResearchWindow,
    Result,
    SessionEvent,
    Usage,
)
from sourcesift.reports import render_report, save_report
from sourcesift.sources import Source, SourceRegistry

__all__ = [
    "AgentSettings",
    "Block",
    "Column",
    "ConfigurationError",
    "ContextDocument",
    "ContextSettings",
    "DataSource",
    "FetchContext",
    "Figure",
    "InputError",
    "Limits",
    "ModelError",
    "Record",
    "Reference",
    "ReportsSettings",
    "Request",
    "ResearchWindow",
    "Result",
    "Session",
    "SessionEvent",
    "SessionsSettings",
    "Settings",
    "Source",
    "SourceRegistry",
    "SourceResult",
    "SourceSift",
    "SourceSiftError",
    "SourcesSettings",
    "Stat",
    "StatView",
    "Table",
    "TableView",
    "Usage",
    "Widget",
    "hello",
    "load_settings",
    "render_report",
    "save_report",
    "source",
    "widget",
]


def hello() -> str:
    """Return the original scaffold greeting, retained for compatibility."""
    return "Hello from sourcesift!"
