"""SourceSift: a Python SDK for requests with explicit document context."""

from sourcesift.core.application import SourceSift
from sourcesift.core.config import (
    AgentSettings,
    ContextSettings,
    Limits,
    Settings,
    SourcesSettings,
    load_settings,
)
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
    Usage,
)
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
    "Request",
    "ResearchWindow",
    "Result",
    "Settings",
    "Source",
    "SourceRegistry",
    "SourceSift",
    "SourceSiftError",
    "SourcesSettings",
    "Usage",
    "hello",
    "load_settings",
]


def hello() -> str:
    """Return the original scaffold greeting, retained for compatibility."""
    return "Hello from sourcesift!"
