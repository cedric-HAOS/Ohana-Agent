"""Results exposed by the Shelly telemetry check."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ShellyTelemetryValue:
    """One validated Home Assistant sensor value."""

    entity_id: str
    value: float | None = None
    unit: str | None = None
    reported_at: datetime | None = None
    age_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ShellyTelemetryCheckResult:
    """Freshness result for one Shelly device."""

    device_name: str
    healthy: bool
    power: ShellyTelemetryValue
    energy: ShellyTelemetryValue | None = None
    attempts: int = 1
    error: str | None = None
