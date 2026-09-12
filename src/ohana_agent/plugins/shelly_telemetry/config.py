"""Compatibility aliases for Shelly Telemetry runtime configuration."""

from ohana_agent.plugins.home_assistant_telemetry.config import (
    HomeAssistantTelemetryConfig,
    HomeAssistantTelemetryServiceConfig,
)

ShellyTelemetryConfig = HomeAssistantTelemetryConfig
ShellyTelemetryServiceConfig = HomeAssistantTelemetryServiceConfig

__all__ = ["ShellyTelemetryConfig", "ShellyTelemetryServiceConfig"]
