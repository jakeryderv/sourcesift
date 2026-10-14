"""Application errors safe to display without exposing provider response bodies."""


class SourceSiftError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(SourceSiftError):
    """Configuration or credentials are missing or invalid."""


class InputError(SourceSiftError):
    """A request or context input cannot be used."""


class ModelError(SourceSiftError):
    """The configured model could not complete the request."""
