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


def test_shelly_telemetry_plugin_returns_freshness_observation() -> None:
    check = FakeShellyTelemetryCheck(
        ShellyTelemetryCheckResult(
            device_name="Cuisine",
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
        device_name="Cuisine",
        power_entity_id="sensor.shelly_power",
    )

    assert result.success is True
    assert result.check == "shelly.telemetry.freshness"
    assert result.metadata["power"]["value"] == 0.0


def test_shelly_telemetry_plugin_requires_power_entity() -> None:
    with pytest.raises(ValueError, match="power_entity_id"):
        ShellyTelemetryPlugin().execute(
            device_name="Cuisine",
            power_entity_id="",
        )
