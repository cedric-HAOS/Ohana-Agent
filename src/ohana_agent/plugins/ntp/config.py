"""Runtime configuration used by the NTP plugin."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NTPServerConfig:
    """Configuration for one NTP server."""

    name: str
    address: str
    port: int = 123
    enabled: bool = True
    node_id: str | None = None


@dataclass(frozen=True)
class NTPPolicyConfig:
    """Policy used to evaluate one NTP response."""

    maximum_offset_ms: float = 1000.0
    maximum_stratum: int = 15


@dataclass(frozen=True)
class NTPConfig:
    """Configuration for the NTP plugin."""

    servers: list[NTPServerConfig] = field(default_factory=list)
    timeout: float = 2.0
    retries: int = 1
    policy: NTPPolicyConfig = field(default_factory=NTPPolicyConfig)
