"""Opt-in live OpenRouter smoke test, excluded from hooks and normal CI."""

import os

import pytest

from sourcesift import SourceSift, load_settings

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("SOURCESIFT_LIVE_TEST") != "1",
        reason="Set SOURCESIFT_LIVE_TEST=1 to explicitly enable paid inference.",
    ),
]


def test_live_document_summary():
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.fail("Set OPENROUTER_API_KEY before opting into the live check.")
    if not os.environ.get("SOURCESIFT_MODEL"):
        pytest.fail("Set SOURCESIFT_MODEL to the model being evaluated.")
    from sourcesift import ContextDocument, Request

    settings = load_settings(
        overrides={
            "context": {"files": [], "instructions_file": None},
            "limits": {
                "max_input_bytes": 4096,
                "max_output_tokens": 2048,
                "timeout_seconds": 60,
            },
        }
    )
    result = SourceSift(settings).run_sync(
        Request(
            prompt="What is the project name and how many checks passed? Answer in one sentence.",
            context=(
                ContextDocument(
                    name="synthetic-note",
                    text="Project Cedar completed all seven checks on its sample documents.",
                ),
            ),
        )
    )
    assert "cedar" in result.answer.lower()
    assert "seven" in result.answer.lower() or "7" in result.answer
    assert result.usage.requests == 1
    assert result.limitations
