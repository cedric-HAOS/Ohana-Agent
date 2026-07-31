"""Compatibility aliases for the former Shelly Telemetry configuration."""

from configuration.home_assistant_telemetry import (
    HomeAssistantTelemetryDevicePluginConfig,
    HomeAssistantTelemetryPluginConfig,
)

ShellyTelemetryDevicePluginConfig = HomeAssistantTelemetryDevicePluginConfig
ShellyTelemetryPluginConfig = HomeAssistantTelemetryPluginConfig

__all__ = [
    "ShellyTelemetryDevicePluginConfig",
    "ShellyTelemetryPluginConfig",
]
