from dataclasses import dataclass


@dataclass
class DNSCapabilityRuntime:
    """Runtime state for the DNS capability."""

    total_servers: int = 0
    healthy_servers: int = 0
    failed_servers: int = 0
    healthy: bool | None = None

    def update(
        self,
        total_servers: int,
        healthy_servers: int,
        minimum_healthy_servers: int,
    ) -> None:
        self.total_servers = total_servers
        self.healthy_servers = healthy_servers
        self.failed_servers = total_servers - healthy_servers
        self.healthy = healthy_servers >= minimum_healthy_servers
