"""Compatibility aliases for Shelly Telemetry runtime configuration."""

from plugins.home_assistant_telemetry.home_assistant_telemetry_config import (
    HomeAssistantTelemetryConfig,
    HomeAssistantTelemetryServiceConfig,
)

ShellyTelemetryConfig = HomeAssistantTelemetryConfig
ShellyTelemetryServiceConfig = HomeAssistantTelemetryServiceConfig

__all__ = ["ShellyTelemetryConfig", "ShellyTelemetryServiceConfig"]
