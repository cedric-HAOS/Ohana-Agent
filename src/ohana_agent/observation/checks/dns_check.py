from ohana_agent.observation.checks.base_check import BaseCheck
from ohana_agent.observation.observer_result import ObserverResult
from ohana_agent.plugins.dns.resolver import DNSResolver


class DNSCheck(BaseCheck):
    """DNS observation check."""

    def __init__(
        self,
        hostname: str,
        server: str,
        resolver: DNSResolver | None = None,
    ) -> None:
        self.hostname = hostname
        self.server = server
        self.resolver = resolver or DNSResolver()

    @property
    def name(self) -> str:
        """Return the check name."""
        return "dns.resolve"

    @property
    def description(self) -> str:
        """Return the check description."""
        return f"Resolve {self.hostname} using {self.server}"

    def execute(self) -> ObserverResult:
        """Execute a DNS resolution check."""
        result = self.resolver.resolve(
            hostname=self.hostname,
            server=self.server,
        )

        return ObserverResult(
            success=result.success,
            latency=getattr(result, "latency", 0.0),
            message=result.error,
            check=self.name,
            description=self.description,
            metadata={
                "hostname": result.hostname,
                "server": result.server,
                "address": result.address,
            },
        )
