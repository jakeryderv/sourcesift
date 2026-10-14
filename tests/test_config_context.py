"""Configuration precedence, private diagnostics, and bounded input behavior."""

import io

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sourcesift.core.config import Limits, Settings, load_settings
from sourcesift.core.context import prepare_request
from sourcesift.errors import ConfigurationError, InputError
from sourcesift.models import ContextDocument, Request


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    for name in (
        "SOURCESIFT_CONFIG",
        "SOURCESIFT_MODEL",
        "SOURCESIFT_REASONING_EFFORT",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "sourcesift.core.config.default_config_path", lambda: tmp_path / "absent.toml"
    )


def test_defaults_and_selected_missing_file(tmp_path):
    assert load_settings() == Settings()
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_settings(tmp_path / "missing.toml")


def test_configuration_precedence_and_relative_context(monkeypatch, tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '[agent]\nmodel = "example/file"\n[context]\nfiles = ["profile.md"]\n',
        encoding="utf-8",
    )
    assert load_settings(config).agent.model == "example/file"
    assert load_settings(config).context.files == (tmp_path / "profile.md",)
    monkeypatch.setenv("SOURCESIFT_MODEL", "example/environment")
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-key")
    monkeypatch.setenv("SOURCESIFT_CONFIG", str(config))
    assert load_settings().agent.model == "example/environment"
    settings = load_settings(overrides={"agent": {"model": "example/explicit"}})
    assert settings.agent.model == "example/explicit"
    assert settings.agent.api_key is not None
    assert settings.agent.api_key.get_secret_value() == "private-key"
    assert "private-key" not in repr(settings)
    assert "private-key" not in settings.model_dump_json()
    monkeypatch.setenv("SOURCESIFT_MODEL", "invalid")
    assert (
        load_settings(overrides={"agent": {"model": "example/override"}}).agent.model
        == "example/override"
    )


@pytest.mark.parametrize(
    "content",
    [
        b"[malformed",
        b"\xff",
        b"x" * 65537,
        b'[agent]\napi_key="private-key"',
        b"[agent]\nmodel=99",
        b"[limits]\ntimeout_seconds=nan",
        b"[context]\nfiles=[23]",
        b'[agent]\nmisspelled="private-key"',
    ],
)
def test_bad_configuration_is_safe(content, tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(content)
    with pytest.raises(ConfigurationError) as error:
        load_settings(path)
    assert "private-key" not in str(error.value)
    assert "99" not in str(error.value)


def test_order_and_roles(tmp_path):
    background = tmp_path / "profile.md"
    document = tmp_path / "report.md"
    background.write_text("background", encoding="utf-8")
    document.write_text("report", encoding="utf-8")
    settings = Settings.model_validate({"context": {"files": [background]}})
    request = Request(
        prompt="summarize", context=(ContextDocument(name="sdk", text="sdk text"),)
    )
    result = prepare_request(
        request, settings, files=[document], stdin=io.BytesIO(b"piped")
    )
    assert [(d.name, d.text, d.role) for d in result.context] == [
        ("profile.md", "background", "background"),
        ("sdk", "sdk text", "document"),
        ("report.md", "report", "document"),
        ("stdin", "piped", "document"),
    ]
    assert request.context[0].text == "sdk text"


@pytest.mark.parametrize("data", [b"\xff", b"text\0binary", b"x" * 100])
def test_invalid_or_oversized_stdin(data):
    with pytest.raises(InputError):
        prepare_request(
            Request(prompt="task"),
            Settings(limits=Limits(max_input_bytes=30)),
            stdin=io.BytesIO(data),
        )


def test_empty_stdin_and_blank_prompt():
    assert (
        prepare_request(Request(prompt="task"), Settings(), stdin=io.BytesIO()).context
        == ()
    )
    with pytest.raises(ValidationError):
        Request(prompt=" \n")


def test_file_errors_and_count_limits(tmp_path):
    for path in (tmp_path, tmp_path / "missing"):
        with pytest.raises(InputError):
            prepare_request(Request(prompt="task"), Settings(), files=[path])
    with pytest.raises(InputError, match="Too many"):
        prepare_request(
            Request(prompt="task"),
            Settings(limits=Limits(max_context_files=0)),
            files=[tmp_path / "missing"],
        )


@given(
    st.text(
        alphabet=st.characters(exclude_categories=("Cs",), exclude_characters="\0"),
        max_size=100,
    )
)
def test_unicode_budget_counts_bytes_exactly(text):
    request = Request(prompt="task", context=(ContextDocument(name="sdk", text=text),))
    size = len(("tasksdk" + text).encode("utf-8"))
    assert (
        prepare_request(request, Settings(limits=Limits(max_input_bytes=size)))
        == request
    )
    with pytest.raises(InputError):
        prepare_request(request, Settings(limits=Limits(max_input_bytes=size - 1)))
