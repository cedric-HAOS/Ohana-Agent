"""Compatibility alias for the former Shelly telemetry builder."""

from builder.home_assistant_telemetry_configuration_builder import (
    HomeAssistantTelemetryConfigurationBuilder,
)

ShellyTelemetryConfigurationBuilder = HomeAssistantTelemetryConfigurationBuilder

__all__ = ["ShellyTelemetryConfigurationBuilder"]
