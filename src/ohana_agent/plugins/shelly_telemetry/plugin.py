"""Compatibility alias for the former Shelly Telemetry plugin class."""

from ohana_agent.plugins.home_assistant_telemetry.plugin import (
    HomeAssistantTelemetryPlugin,
)

ShellyTelemetryPlugin = HomeAssistantTelemetryPlugin

__all__ = ["ShellyTelemetryPlugin"]
