from dataclasses import dataclass, field


@dataclass(frozen=True)
class DNSServerConfig:
    """Configuration for one DNS server."""

    name: str
    address: str
    enabled: bool = True
    node_id: str | None = None


@dataclass(frozen=True)
class DNSPolicyConfig:
    """Policy used to evaluate DNS capability health."""

    minimum_healthy_servers: int = 1


@dataclass(frozen=True)
class DNSConfig:
    """Configuration for the DNS plugin."""

    servers: list[DNSServerConfig] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    timeout: float = 2.0
    retries: int = 1
    policy: DNSPolicyConfig = field(default_factory=DNSPolicyConfig)
