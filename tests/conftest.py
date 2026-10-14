"""Shared property-test settings; CI trades example replay for reproducibility."""

import os

from hypothesis import settings

settings.register_profile("ci", max_examples=200, derandomize=True, deadline=None)
if os.environ.get("CI") == "true":
    settings.load_profile("ci")
