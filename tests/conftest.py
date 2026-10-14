"""Shared property-test settings; CI trades example replay for reproducibility."""

import os

import pytest
from hypothesis import settings
from pydantic_ai import models

settings.register_profile("ci", max_examples=200, derandomize=True, deadline=None)
if os.environ.get("CI") == "true":
    settings.load_profile("ci")


@pytest.fixture(autouse=True)
def model_requests_require_opt_in(monkeypatch, request):
    """Ordinary tests cannot accidentally call a paid model."""
    monkeypatch.setattr(
        models, "ALLOW_MODEL_REQUESTS", bool(request.node.get_closest_marker("network"))
    )
