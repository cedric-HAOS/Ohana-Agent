# plugins/dns/dns_events.py

from dataclasses import dataclass


@dataclass(frozen=True)
class DNSCheckStarted:
    """Event emitted when a DNS check starts."""

    hostname: str


@dataclass(frozen=True)
class DNSCheckSucceeded:
    """Event emitted when a DNS check succeeds."""

    hostname: str
    address: str | None = None


@dataclass(frozen=True)
class DNSCheckFailed:
    """Event emitted when a DNS check fails."""

    hostname: str
    error: str | None = None
