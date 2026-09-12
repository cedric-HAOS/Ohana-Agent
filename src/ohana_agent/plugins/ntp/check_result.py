"""Result exposed by the NTP check."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NTPCheckResult:
    """Result of an NTP capability check."""

    server: str
    port: int
    healthy: bool
    source_address: str | None = None
    offset_ms: float | None = None
    round_trip_ms: float | None = None
    stratum: int | None = None
    version: int | None = None
    leap_indicator: int | None = None
    attempts: int = 1
    error: str | None = None
