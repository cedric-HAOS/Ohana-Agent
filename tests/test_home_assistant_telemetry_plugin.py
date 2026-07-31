"""Tests for the Home Assistant telemetry observation plugin."""

import pytest

from plugins.home_assistant_telemetry.home_assistant_telemetry_config import (
    HomeAssistantTelemetryConfig,
)
from plugins.home_assistant_telemetry.home_assistant_telemetry_plugin import (
    HomeAssistantTelemetryPlugin,
)
from plugins.home_assistant_telemetry.home_assistant_telemetry_result import (
    HomeAssistantTelemetryCheckResult,
    HomeAssistantTelemetryValue,
)


class FakeHomeAssistantTelemetryCheck:
    def __init__(self, result: HomeAssistantTelemetryCheckResult) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    def check(self, service_name: str, primary_entity_id: str, **kwargs):
        self.calls.append((service_name, primary_entity_id, kwargs))
        return self.result


def test_home_assistant_telemetry_plugin_returns_service_observation() -> None:
    check = FakeHomeAssistantTelemetryCheck(
        HomeAssistantTelemetryCheckResult(
            service_name="Télémétrie cuisine",
            healthy=True,
            primary=HomeAssistantTelemetryValue(
                entity_id="sensor.kitchen_power", value=0.0, unit="W"
            ),
        )
    )
    plugin = HomeAssistantTelemetryPlugin(
        check=check,
        config=HomeAssistantTelemetryConfig(access_token="secret"),
    )

    result = plugin.execute(
        service_id="telemetry-kitchen",
        service_name="Télémétrie cuisine",
        node_id="device-kitchen",
        primary_entity_id="sensor.kitchen_power",
        maximum_age_seconds=600,
    )

    assert result.success is True
    assert result.check == "home_assistant.telemetry.freshness"
    assert result.metadata["target_type"] == "service"
    assert result.metadata["service_id"] == "telemetry-kitchen"
    assert result.metadata["node_id"] == "device-kitchen"
    assert result.metadata["maximum_age_seconds"] == 600
    assert result.metadata["primary"]["value"] == 0.0
    assert check.calls[0][2]["maximum_age_seconds"] == 600


def test_plugin_accepts_legacy_entity_arguments() -> None:
    check = FakeHomeAssistantTelemetryCheck(
        HomeAssistantTelemetryCheckResult(
            service_name="Ancien service Shelly",
            healthy=True,
            primary=HomeAssistantTelemetryValue(
                entity_id="sensor.shelly_power", value=4.2, unit="W"
            ),
        )
    )
    result = HomeAssistantTelemetryPlugin(check=check).execute(
        service_id="legacy-shelly",
        service_name="Ancien service Shelly",
        node_id="shelly-kitchen",
        power_entity_id="sensor.shelly_power",
        energy_entity_id="sensor.shelly_energy",
    )
    assert result.success is True
    assert check.calls[0][1] == "sensor.shelly_power"
    assert check.calls[0][2]["secondary_entity_id"] == "sensor.shelly_energy"


def test_home_assistant_telemetry_plugin_requires_primary_entity() -> None:
    with pytest.raises(ValueError, match="primary_entity_id"):
        HomeAssistantTelemetryPlugin().execute(
            service_id="telemetry-kitchen",
            service_name="Télémétrie cuisine",
            node_id="device-kitchen",
            primary_entity_id="",
        )
