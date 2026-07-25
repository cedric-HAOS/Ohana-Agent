"""DNS check bound to one configured DNS server."""

from dataclasses import dataclass, field

from plugins.dns.dns_check import DNSCheck
from plugins.dns.dns_check_result import DNSCheckResult


@dataclass(slots=True)
class ConfiguredDNSCheck:
    """Execute DNS queries through one explicit DNS server."""

    server: str
    check_engine: DNSCheck = field(default_factory=DNSCheck)

    def __post_init__(self) -> None:
        """Validate the configured server."""
        if not self.server.strip():
            raise ValueError("server must not be empty.")

    def check(
        self,
        hostname: str,
        server: str | None = None,
    ) -> DNSCheckResult:
        """Resolve a hostname through an explicit or configured server."""
        return self.check_engine.check(
            hostname=hostname,
            server=server or self.server,
        )
