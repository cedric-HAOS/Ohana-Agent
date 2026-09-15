"""Filtering shared by historical log references and AI evidence construction."""

import re

_SESSION_PATH = re.compile(r"(/stok=)[^/\s\"'<>]+", re.IGNORECASE)


def redact_session_paths(value: str) -> str:
    """Mask camera session paths while keeping the diagnostic endpoint shape."""
    return _SESSION_PATH.sub(r"\1[redacted]", value)
