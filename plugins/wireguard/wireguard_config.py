"""Runtime configuration used by the Freebox WireGuard plugin."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class WireGuardServiceConfig:
    """Configuration for one WireGuard server exposed by a Freebox."""

    name: str
    base_url: str
    server_name: str = "wireguard"
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class WireGuardConfig:
    """Runtime configuration for Freebox WireGuard checks."""

    services: list[WireGuardServiceConfig] = field(default_factory=list)
    timeout: float = 3.0
    retries: int = 1
    app_id: str = "fr.ohana.agent"
    app_version: str = "1.7.4"
    app_token: str | None = None
    verify_tls: bool = False
