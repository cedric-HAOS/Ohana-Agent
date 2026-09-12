"""Compatibility alias for the former Shelly telemetry builder."""

from ohana_agent.configuration.builders.home_assistant_telemetry import (
    HomeAssistantTelemetryConfigurationBuilder,
)

ShellyTelemetryConfigurationBuilder = HomeAssistantTelemetryConfigurationBuilder

__all__ = ["ShellyTelemetryConfigurationBuilder"]
