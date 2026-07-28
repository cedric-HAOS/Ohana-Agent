"""Result exposed by the Z-Wave health check."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ZWaveHealthResult:
    """Result of one Z-Wave JS UI health request."""

    url: str
    healthy: bool
    status_code: int | None = None
    response: str | None = None
    attempts: int = 1
    error: str | None = None
