"""Result exposed by the Freebox WireGuard check."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WireGuardCheckResult:
    """Result of one Freebox WireGuard server inspection."""

    service_name: str
    base_url: str
    server_name: str
    healthy: bool
    state: str | None = None
    connection_count: int | None = None
    authenticated_connection_count: int | None = None
    attempts: int = 1
    error: str | None = None
