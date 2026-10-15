"""Public HTTP URL normalization shared by sources and retrieval."""

import ipaddress
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class RetrievalError(Exception):
    """A safe, human-readable retrieval failure (never a response body)."""


def normalize_url(value: str) -> str:
    """Normalize public HTTP(S) URLs, dropping fragments and tracking parameters."""
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
        port = parts.port
        if (
            parts.scheme not in {"http", "https"}
            or not host
            or parts.username is not None
            or parts.password is not None
            or port not in {None, 80, 443}
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            or "\\" in value
            or len(value) > 4096
        ):
            raise ValueError
        if host.rstrip(".") == "localhost" or host.endswith((".localhost", ".local")):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global or address.is_multicast or address.is_reserved:
                raise ValueError
        authority = f"[{host}]" if ":" in host else host
        if port is not None and port != (443 if parts.scheme == "https" else 80):
            authority += f":{port}"
        query = urlencode(
            [
                (key, val)
                for key, val in parse_qsl(parts.query, keep_blank_values=True)
                if not key.lower().startswith("utm_")
                and key.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
            ]
        )
        return urlunsplit((parts.scheme, authority, parts.path or "/", query, ""))
    except (ValueError, UnicodeError):
        raise RetrievalError(
            "URL must be public HTTP(S), without credentials or an unusual port."
        ) from None


def hostname(url: str) -> str:
    """Return a normalized hostname for provenance, not a publisher claim."""
    return urlsplit(url).hostname or ""
