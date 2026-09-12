# plugins/dns/dns_check_result.py

from dataclasses import dataclass


@dataclass(frozen=True)
class DNSCheckResult:
    """Result of a DNS capability check."""

    hostname: str
    healthy: bool
    server: str | None = None
    address: str | None = None
    error: str | None = None
