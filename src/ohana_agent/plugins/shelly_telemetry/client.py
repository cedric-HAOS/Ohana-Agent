"""Compatibility aliases for the former Shelly telemetry client."""

from ohana_agent.plugins.home_assistant_telemetry.client import (
    HomeAssistantEntityState,
    HomeAssistantTelemetryClient,
)

__all__ = ["HomeAssistantEntityState", "HomeAssistantTelemetryClient"]
