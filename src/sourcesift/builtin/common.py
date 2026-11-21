"""Helpers for reading JSON data services defensively."""

import json
import math

from sourcesift.retrieval.http import Page
from sourcesift.retrieval.urls import RetrievalError


def json_object(page: Page) -> dict[str, object]:
    try:
        data = json.loads(page.body)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise RetrievalError("The data service returned an unexpected response.")
    return data


def one_line(value: object, limit: int = 300) -> str:
    """One bounded line from an untrusted field; absent values become empty."""
    return " ".join(str(value).split())[:limit] if value is not None else ""


def number(value: object) -> float | None:
    """A finite number from an untrusted field, or None."""
    try:
        result = float(str(value).replace(",", ""))
    except ValueError:
        return None
    return result if math.isfinite(result) else None
