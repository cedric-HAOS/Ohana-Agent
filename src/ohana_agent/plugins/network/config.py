"""Runtime configuration used by the network presence plugin."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class NetworkDeviceConfig:
    """One topology device eligible for presence checks."""

    name: str
    label: str
    address: str
    node_id: str | None = None
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class NetworkConfig:
    """Runtime configuration for network presence checks."""

    devices: list[NetworkDeviceConfig] = field(default_factory=list)
    timeout: float = 1.0
    retries: int = 0
    failure_threshold: int = 3
