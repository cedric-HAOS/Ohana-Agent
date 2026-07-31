"""Compatibility result types for the former Shelly telemetry plugin."""

from dataclasses import dataclass

from plugins.home_assistant_telemetry.home_assistant_telemetry_result import (
    HomeAssistantTelemetryCheckResult,
    HomeAssistantTelemetryValue,
)

ShellyTelemetryValue = HomeAssistantTelemetryValue


@dataclass(frozen=True, slots=True)
class ShellyTelemetryCheckResult:
    """Legacy result shape translated by the compatibility check wrapper."""

    device_name: str
    healthy: bool
    power: ShellyTelemetryValue
    energy: ShellyTelemetryValue | None = None
    attempts: int = 1
    error: str | None = None


__all__ = [
    "HomeAssistantTelemetryCheckResult",
    "ShellyTelemetryCheckResult",
    "ShellyTelemetryValue",
]
