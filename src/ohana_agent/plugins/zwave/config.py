"""Runtime configuration used by the Z-Wave plugin."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ZWaveServiceConfig:
    """Configuration for one Z-Wave JS Server service."""

    name: str
    url: str
    enabled: bool = True
    node_id: str | None = None


@dataclass(frozen=True, slots=True)
class ZWaveConfig:
    """Runtime configuration for Z-Wave health checks."""

    services: list[ZWaveServiceConfig] = field(default_factory=list)
    timeout: float = 3.0
    retries: int = 1
    verify_tls: bool = True
    last_seen_alert_minutes: int | None = None
    sleeping_last_seen_alert_minutes: int | None = None

    def silence_threshold_minutes(self, *, can_sleep: bool) -> int | None:
        """Return the allowed silence for a node, or None when not monitored."""
        return (
            self.sleeping_last_seen_alert_minutes
            if can_sleep
            else self.last_seen_alert_minutes
        )
