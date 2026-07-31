"""Compatibility alias for the former Shelly Telemetry plugin class."""

from plugins.home_assistant_telemetry.home_assistant_telemetry_plugin import (
    HomeAssistantTelemetryPlugin,
)

ShellyTelemetryPlugin = HomeAssistantTelemetryPlugin

__all__ = ["ShellyTelemetryPlugin"]
