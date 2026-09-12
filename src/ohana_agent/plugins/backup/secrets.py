"""Resolve backup secrets without exposing their values through administration."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_backup_secret(environment_file: str, name: str) -> str | None:
    """Return one secret from the process environment or the protected file."""
    value = os.getenv(name)
    if value:
        return value

    try:
        lines = Path(environment_file).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None

    for line in lines:
        normalized = line.strip()
        if not normalized or normalized.startswith("#") or "=" not in normalized:
            continue
        key, candidate = normalized.split("=", 1)
        if key.strip() != name:
            continue
        candidate = candidate.strip()
        if (
            len(candidate) >= 2
            and candidate[0] == candidate[-1]
            and candidate[0] in {'"', "'"}
        ):
            candidate = candidate[1:-1]
        return candidate or None
    return None
