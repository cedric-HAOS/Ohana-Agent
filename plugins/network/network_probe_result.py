"""Result returned by a low-level network presence probe."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NetworkProbeResult:
    """Describe whether a network address could be reached."""

    address: str
    reachable: bool | None
    method: str | None = None
    latency_ms: float | None = None
    attempts: int = 1
    error: str | None = None
