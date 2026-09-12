"""Compatibility alias for the former Shelly telemetry loader."""

from ohana_agent.configuration.loaders.home_assistant_telemetry import (
    HomeAssistantTelemetryConfigLoader,
)

ShellyTelemetryConfigLoader = HomeAssistantTelemetryConfigLoader

__all__ = ["ShellyTelemetryConfigLoader"]
