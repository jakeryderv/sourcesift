"""The base for immutable, validated public data."""

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    """Immutable, validated public data."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
