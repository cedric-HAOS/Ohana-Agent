"""Runtime configuration used by the Z-Wave plugin."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ZWaveServiceConfig:
    """Configuration for one Z-Wave JS Server service."""

    name: str
    url: str
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ZWaveConfig:
    """Runtime configuration for Z-Wave health checks."""

    services: list[ZWaveServiceConfig] = field(default_factory=list)
    timeout: float = 3.0
    retries: int = 1
    verify_tls: bool = True
