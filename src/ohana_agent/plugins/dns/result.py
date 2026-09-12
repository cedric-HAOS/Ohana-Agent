# plugins/dns/dns_result.py

from dataclasses import dataclass


@dataclass(frozen=True)
class DNSResult:
    """Result of a DNS resolution attempt."""

    hostname: str
    success: bool
    server: str | None = None
    address: str | None = None
    error: str | None = None
