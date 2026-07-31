"""Compatibility aliases for the former Shelly telemetry client."""

from plugins.home_assistant_telemetry.home_assistant_telemetry_client import (
    HomeAssistantEntityState,
    HomeAssistantTelemetryClient,
)

__all__ = ["HomeAssistantEntityState", "HomeAssistantTelemetryClient"]
