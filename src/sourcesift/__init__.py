"""SourceSift: a Python SDK for requests with explicit document context."""

from sourcesift.artifacts import artifact_from_answer, render_qmd, save_artifacts
from sourcesift.core.application import SourceSift
from sourcesift.core.config import (
    AgentSettings,
    ArtifactsSettings,
    ContextSettings,
    Limits,
    SessionsSettings,
    Settings,
    SourcesSettings,
    load_settings,
)
from sourcesift.core.session import Session
from sourcesift.data import Column, Figure, Table
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
    source,
)
from sourcesift.figures import render_png
from sourcesift.models import (
    Artifact,
    ContextDocument,
    Reference,
    Request,
    ResearchWindow,
    Result,
    SessionEvent,
    Usage,
)
from sourcesift.sources import Source, SourceRegistry

__all__ = [
    "AgentSettings",
    "Artifact",
    "ArtifactsSettings",
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
    "Table",
    "Usage",
    "artifact_from_answer",
    "hello",
    "load_settings",
    "render_png",
    "render_qmd",
    "save_artifacts",
    "source",
]


def hello() -> str:
    """Return the original scaffold greeting, retained for compatibility."""
    return "Hello from sourcesift!"
