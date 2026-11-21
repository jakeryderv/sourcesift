"""Application errors whose messages are safe to display.

Messages never contain raw provider response bodies. ``ModelError`` keeps the raw
provider response separately in ``detail`` for explicit debugging.
"""


class SourceSiftError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(SourceSiftError):
    """Configuration or credentials are missing or invalid."""


class InputError(SourceSiftError):
    """A request or context input cannot be used."""


class ModelError(SourceSiftError):
    """The configured model could not complete the request.

    Attributes:
        status_code: HTTP status returned by the provider, when there was one.
        detail: Raw provider or runtime error text with the API key redacted. It
            is not part of the message; show it only when debugging is requested.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
