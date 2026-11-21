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
from sourcesift.errors import (
    ConfigurationError,
    InputError,
    ModelError,
    SourceSiftError,
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
    "ConfigurationError",
    "ContextDocument",
    "ContextSettings",
    "InputError",
    "Limits",
    "ModelError",
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
    "SourceSift",
    "SourceSiftError",
    "SourcesSettings",
    "Usage",
    "hello",
    "load_settings",
    "render_report",
    "save_report",
]


def hello() -> str:
    """Return the original scaffold greeting, retained for compatibility."""
    return "Hello from sourcesift!"
