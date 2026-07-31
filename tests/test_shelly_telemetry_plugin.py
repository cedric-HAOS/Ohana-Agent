"""Tests for the Shelly telemetry observation plugin."""

import pytest

from plugins.shelly_telemetry.shelly_telemetry_config import ShellyTelemetryConfig
from plugins.shelly_telemetry.shelly_telemetry_plugin import ShellyTelemetryPlugin
from plugins.shelly_telemetry.shelly_telemetry_result import (
    ShellyTelemetryCheckResult,
    ShellyTelemetryValue,
)


class FakeShellyTelemetryCheck:
    def __init__(self, result: ShellyTelemetryCheckResult) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    def check(self, device_name: str, power_entity_id: str, **kwargs):
        self.calls.append((device_name, power_entity_id, kwargs))
        return self.result


def test_shelly_telemetry_plugin_returns_service_observation() -> None:
    check = FakeShellyTelemetryCheck(
        ShellyTelemetryCheckResult(
            device_name="Télémétrie cuisine",
            healthy=True,
            power=ShellyTelemetryValue(
                entity_id="sensor.shelly_power",
                value=0.0,
                unit="W",
            ),
        )
    )
    plugin = ShellyTelemetryPlugin(
        check=check,
        config=ShellyTelemetryConfig(access_token="secret"),
    )

    result = plugin.execute(
        service_id="shelly-telemetry-cuisine",
        service_name="Télémétrie cuisine",
        node_id="shelly-cuisine",
        power_entity_id="sensor.shelly_power",
        maximum_age_seconds=600,
    )

    assert result.success is True
    assert result.check == "home_assistant.telemetry.freshness"
    assert result.metadata["target_type"] == "service"
    assert result.metadata["service_id"] == "shelly-telemetry-cuisine"
    assert result.metadata["node_id"] == "shelly-cuisine"
    assert result.metadata["maximum_age_seconds"] == 600
    assert result.metadata["power"]["value"] == 0.0
    assert check.calls[0][2]["maximum_age_seconds"] == 600


def test_shelly_telemetry_plugin_requires_primary_entity() -> None:
    with pytest.raises(ValueError, match="primary_entity_id"):
        ShellyTelemetryPlugin().execute(
            service_id="shelly-telemetry-cuisine",
            service_name="Télémétrie cuisine",
            node_id="shelly-cuisine",
            power_entity_id="",
        )
