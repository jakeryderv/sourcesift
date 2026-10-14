"""Resolve TOML, supported environment settings, and explicit overrides."""

import os
import stat
import tomllib
from pathlib import Path
from typing import Any, Literal

from platformdirs import user_config_path
from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict

from sourcesift.errors import ConfigurationError
from sourcesift.models import Contract


class AgentSettings(Contract):
    """OpenRouter model and credential. No model is selected implicitly."""

    model: str | None = None
    reasoning_effort: (
        Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None
    ) = None
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @field_validator("model")
    @classmethod
    def model_identifier(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip() or "/" not in value or any(c.isspace() for c in value)
        ):
            raise ValueError("model must be an OpenRouter provider/model identifier")
        return value


class ContextSettings(Contract):
    """Ordered background files, resolved relative to their configuration file."""

    files: tuple[Path, ...] = ()


class Limits(Contract):
    """Per-request limits. Byte limits count UTF-8 text, not model tokens."""

    max_input_bytes: int = Field(default=131072, ge=1, le=10485760)
    max_context_files: int = Field(default=16, ge=0, le=256)
    timeout_seconds: float = Field(default=60, gt=0, le=600, allow_inf_nan=False)
    max_output_tokens: int = Field(default=2048, ge=1, le=32768)


class Settings(Contract):
    """Resolved application settings shared by the SDK and CLI."""

    agent: AgentSettings = Field(default_factory=AgentSettings)
    context: ContextSettings = Field(default_factory=ContextSettings)
    limits: Limits = Field(default_factory=Limits)


class _Environment(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOURCESIFT_", case_sensitive=True)
    MODEL: str | None = None
    REASONING_EFFORT: str | None = None
    api_key: SecretStr | None = Field(
        default=None, validation_alias="OPENROUTER_API_KEY"
    )


def default_config_path() -> Path:
    """Return the platform's per-user SourceSift config.toml location."""
    return user_config_path("sourcesift", appauthor=False) / "config.toml"


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(
    config_path: str | Path | None = None,
    *,
    overrides: dict[str, Any] | None = None,
) -> Settings:
    """Load defaults < TOML < environment < explicit nested overrides.

    An absent default config is allowed. An explicitly selected config must exist.
    Supported environment variables are SOURCESIFT_CONFIG, SOURCESIFT_MODEL,
    SOURCESIFT_REASONING_EFFORT, and OPENROUTER_API_KEY. No dotenv files or working-directory config are loaded.
    """
    selected = (
        config_path if config_path is not None else os.environ.get("SOURCESIFT_CONFIG")
    )
    try:
        path = (
            Path(selected).expanduser()
            if selected is not None
            else default_config_path()
        ).resolve()
    except (OSError, RuntimeError, ValueError):
        raise ConfigurationError("Cannot resolve the configuration path.") from None
    data: dict[str, Any] = {}
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise ConfigurationError("Configuration must be a regular TOML file.")
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ConfigurationError("Configuration exceeds the 64 KiB limit.")
        data = tomllib.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        if selected is not None:
            raise ConfigurationError(
                "Selected configuration file does not exist."
            ) from None
    except (OSError, UnicodeError, ValueError):
        raise ConfigurationError("Cannot read configuration as UTF-8 TOML.") from None
    # Credentials belong in the environment or SDK, never in TOML.
    if isinstance(data.get("agent"), dict) and "api_key" in data["agent"]:
        raise ConfigurationError(
            "Use OPENROUTER_API_KEY or an SDK override for credentials."
        )
    context = data.get("context")
    if isinstance(context, dict) and isinstance(context.get("files"), list):
        context["files"] = [
            str(path.parent / Path(item).expanduser())
            if isinstance(item, str)
            else item
            for item in context["files"]
        ]
    env = EnvSettingsSource(_Environment)()
    agent_env = {}
    if "MODEL" in env:
        agent_env["model"] = env["MODEL"]
    if "REASONING_EFFORT" in env:
        agent_env["reasoning_effort"] = env["REASONING_EFFORT"]
    if "OPENROUTER_API_KEY" in env:
        agent_env["api_key"] = env["OPENROUTER_API_KEY"]
    if agent_env:
        data = _merge(data, {"agent": agent_env})
    data = _merge(data, overrides or {})
    try:
        settings = Settings.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
        raise ConfigurationError(f"Invalid configuration fields: {fields}.") from None
    return settings
