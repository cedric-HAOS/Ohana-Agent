"""Compatibility aliases for the former Shelly Telemetry configuration."""

from ohana_agent.configuration.home_assistant_telemetry import (
    HomeAssistantTelemetryDevicePluginConfig,
    HomeAssistantTelemetryPluginConfig,
)

ShellyTelemetryDevicePluginConfig = HomeAssistantTelemetryDevicePluginConfig
ShellyTelemetryPluginConfig = HomeAssistantTelemetryPluginConfig

__all__ = [
    "ShellyTelemetryDevicePluginConfig",
    "ShellyTelemetryPluginConfig",
]
