"""Compatibility package for the former Shelly Telemetry plugin."""

from plugins.shelly_telemetry.shelly_telemetry_check import ShellyTelemetryCheck
from plugins.shelly_telemetry.shelly_telemetry_config import (
    ShellyTelemetryConfig,
    ShellyTelemetryServiceConfig,
)
from plugins.shelly_telemetry.shelly_telemetry_plugin import ShellyTelemetryPlugin

__all__ = [
    "ShellyTelemetryCheck",
    "ShellyTelemetryConfig",
    "ShellyTelemetryPlugin",
    "ShellyTelemetryServiceConfig",
]
