"""Runtime configuration used by the DHCP plugin."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DHCPServerConfig:
    """Configuration for one DHCP service."""

    name: str
    address: str
    port: int = 67
    enabled: bool = True
    node_id: str | None = None


@dataclass(frozen=True)
class DHCPPolicyConfig:
    """Policy used to evaluate dnsmasq pool occupation."""

    maximum_pool_usage_percent: float = 90.0


@dataclass(frozen=True)
class DHCPConfig:
    """Configuration for the DHCP observation plugin."""

    servers: list[DHCPServerConfig] = field(default_factory=list)
    main_config_path: Path = Path("/etc/dnsmasq.d/00-ohana.conf")
    leases_path: Path = Path("/var/lib/misc/dnsmasq.leases")
    service_status_command: tuple[str, ...] | None = (
        "/usr/bin/systemctl",
        "is-active",
        "dnsmasq.service",
    )
    timeout: float = 3.0
    policy: DHCPPolicyConfig = field(default_factory=DHCPPolicyConfig)
