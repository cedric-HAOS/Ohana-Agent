"""Compatibility package for the former Shelly Telemetry plugin."""

from ohana_agent.plugins.shelly_telemetry.check import (
    ShellyTelemetryCheck,
)
from ohana_agent.plugins.shelly_telemetry.config import (
    ShellyTelemetryConfig,
    ShellyTelemetryServiceConfig,
)
from ohana_agent.plugins.shelly_telemetry.plugin import (
    ShellyTelemetryPlugin,
)

__all__ = [
    "ShellyTelemetryCheck",
    "ShellyTelemetryConfig",
    "ShellyTelemetryPlugin",
    "ShellyTelemetryServiceConfig",
]
