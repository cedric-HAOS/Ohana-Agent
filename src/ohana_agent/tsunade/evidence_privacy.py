"""Filtering shared by persisted Tsunade evidence and AI evidence construction."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[redacted]"

_SESSION_PATH = re.compile(
    r"(/stok=)[^/\s\"'<>]+",
    re.IGNORECASE,
)

_URL_USERINFO = re.compile(
    r"\b([a-z][a-z0-9+.-]*://)[^/@\s]+@",
    re.IGNORECASE,
)

_AUTHORIZATION = re.compile(
    r"(\bauthorization\s*[:=]\s*(?:bearer|basic)\s+)[^\s,;]+",
    re.IGNORECASE,
)

_BEARER = re.compile(
    r"\b(bearer)\s+[^\s,;]{8,}",
    re.IGNORECASE,
)

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?"
    r"-----END [^-]*PRIVATE KEY-----",
    re.DOTALL,
)

_SENSITIVE_ASSIGNMENT = re.compile(
    r"""
    \b(
        (?:[a-z0-9]+[_-])*token
        |api[_-]?key
        |apikey
        |password
        |passwd
        |client[_-]?secret
        |secret
    )
    (\s*[:=]\s*)
    (?:"[^"]*"|'[^']*'|[^\s&,;]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SENSITIVE_KEYS = {
    "token",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "api_token",
    "apitoken",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "client_secret",
    "clientsecret",
    "secret",
    "authorization",
    "proxy_authorization",
    "proxyauthorization",
    "cookie",
    "set_cookie",
    "setcookie",
    "stok",
    "private_key",
    "privatekey",
    "credentials",
}


def redact_session_paths(value: str) -> str:
    """Mask camera session paths while keeping the diagnostic endpoint shape."""
    return _SESSION_PATH.sub(r"\1[redacted]", value)


def redact_sensitive_text(value: str) -> str:
    """Mask common credentials while preserving useful diagnostic context."""
    value = _PRIVATE_KEY.sub("[redacted-private-key]", value)
    value = redact_session_paths(value)
    value = _URL_USERINFO.sub(r"\1[redacted]@", value)
    value = _AUTHORIZATION.sub(r"\1[redacted]", value)
    value = _BEARER.sub(r"\1 [redacted]", value)
    value = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        value,
    )
    return value


def redact_sensitive_value(value: Any) -> Any:
    """Recursively sanitize structured evidence without changing its shape."""
    if isinstance(value, str):
        return redact_sensitive_text(value)

    if isinstance(value, dict):
        return {
            key: (
                REDACTED if _is_sensitive_key(key) else redact_sensitive_value(content)
            )
            for key, content in value.items()
        }

    if isinstance(value, list):
        return [redact_sensitive_value(content) for content in value]

    if isinstance(value, tuple):
        return tuple(redact_sensitive_value(content) for content in value)
    return value


def _is_sensitive_key(value: object) -> bool:
    key = re.sub(
        r"[^a-z0-9]+",
        "_",
        str(value).casefold(),
    ).strip("_")

    return key in _SENSITIVE_KEYS or key.endswith(
        (
            "_token",
            "_password",
            "_passwd",
            "_secret",
            "_api_key",
        )
    )
