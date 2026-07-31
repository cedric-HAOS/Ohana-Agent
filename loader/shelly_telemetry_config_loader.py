"""Compatibility alias for the former Shelly telemetry loader."""

from loader.home_assistant_telemetry_config_loader import (
    HomeAssistantTelemetryConfigLoader,
)

ShellyTelemetryConfigLoader = HomeAssistantTelemetryConfigLoader

__all__ = ["ShellyTelemetryConfigLoader"]
