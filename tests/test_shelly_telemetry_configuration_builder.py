"""Tests for Shelly telemetry runtime configuration construction."""

from builder import ShellyTelemetryConfigurationBuilder
from configuration.shelly_telemetry import (
    ShellyTelemetryDevicePluginConfig,
    ShellyTelemetryPluginConfig,
)


def test_shelly_telemetry_builder_copies_validated_devices() -> None:
    runtime = ShellyTelemetryConfigurationBuilder().build(
        ShellyTelemetryPluginConfig(
            access_token="secret",
            access_token_environment_variable=None,
            devices=[
                ShellyTelemetryDevicePluginConfig(
                    name="Cuisine",
                    power_entity_id="sensor.shelly_cuisine_power",
                    energy_entity_id="sensor.shelly_cuisine_energy",
                )
            ],
        )
    )

    assert runtime.access_token == "secret"
    assert runtime.devices[0].name == "Cuisine"
    assert runtime.devices[0].energy_entity_id == "sensor.shelly_cuisine_energy"
