"""Result exposed by the DHCP status check."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DHCPCheckResult:
    """Result of one local dnsmasq capability check."""

    server: str
    port: int
    service_id: str
    healthy: bool
    service_active: bool | None = None
    range_start: str | None = None
    range_end: str | None = None
    pool_size: int | None = None
    lease_count: int = 0
    available_address_count: int | None = None
    expired_lease_count: int = 0
    pool_usage_percent: float | None = None
    status_output: str | None = None
    error: str | None = None
