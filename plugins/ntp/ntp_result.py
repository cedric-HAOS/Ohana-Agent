"""Raw result returned by the SNTP client."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NTPResult:
    """Result of one SNTP request."""

    server: str
    port: int
    success: bool
    source_address: str | None = None
    offset_ms: float | None = None
    round_trip_ms: float | None = None
    stratum: int | None = None
    version: int | None = None
    leap_indicator: int | None = None
    error: str | None = None
