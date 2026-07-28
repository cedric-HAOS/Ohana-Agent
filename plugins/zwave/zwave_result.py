"""Result exposed by the Z-Wave health check."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ZWaveHealthResult:
    """Result of one Z-Wave JS health request."""

    url: str
    healthy: bool
    status_code: int | None = None
    response: str | None = None
    server_version: str | None = None
    driver_version: str | None = None
    home_id: str | None = None
    node_count: int | None = None
    attempts: int = 1
    error: str | None = None
