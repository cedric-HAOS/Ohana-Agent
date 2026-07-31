"""Results exposed by the Home Assistant telemetry check."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class HomeAssistantTelemetryValue:
    """One validated Home Assistant entity value."""

    entity_id: str
    value: float | None = None
    unit: str | None = None
    reported_at: datetime | None = None
    age_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class HomeAssistantTelemetryCheckResult:
    """Freshness result for one Home Assistant telemetry service."""

    service_name: str
    healthy: bool
    primary: HomeAssistantTelemetryValue
    secondary: HomeAssistantTelemetryValue | None = None
    attempts: int = 1
    error: str | None = None

    @property
    def device_name(self) -> str:
        """Deprecated alias for service_name."""
        return self.service_name

    @property
    def power(self) -> HomeAssistantTelemetryValue:
        """Deprecated alias for primary."""
        return self.primary

    @property
    def energy(self) -> HomeAssistantTelemetryValue | None:
        """Deprecated alias for secondary."""
        return self.secondary
