"""Tests for the Home Assistant telemetry observation plugin."""

import pytest

from ohana_agent.plugins.home_assistant_telemetry.config import (
    HomeAssistantTelemetryConfig,
)
from ohana_agent.plugins.home_assistant_telemetry.plugin import (
    HomeAssistantTelemetryPlugin,
)
from ohana_agent.plugins.home_assistant_telemetry.result import (
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


def _failing(value: float | None, error: str) -> FakeHomeAssistantTelemetryCheck:
    return FakeHomeAssistantTelemetryCheck(
        HomeAssistantTelemetryCheckResult(
            service_name="Mesure Puissance",
            healthy=False,
            primary=HomeAssistantTelemetryValue(
                entity_id="sensor.sun_01_power", value=value, unit="W"
            ),
            error=error,
        )
    )


def _run(plugin: HomeAssistantTelemetryPlugin):
    return plugin.execute(
        service_id="mesure-puissance",
        service_name="Mesure Puissance",
        node_id="sun-01",
        primary_entity_id="sensor.sun_01_power",
        maximum_age_seconds=600,
    )


def test_an_entity_missing_while_home_assistant_restarts_is_degraded_first(
    monkeypatch,
) -> None:
    # HA-01 update, 28 September: "Entity not found" for five minutes, and
    # SUN-01 was reported critical although nothing was broken.
    from ohana_agent.infrastructure.enums import HealthStatus
    from ohana_agent.plugins.home_assistant_telemetry import plugin as module

    clock = [1000.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    failing = _failing(
        None, 'Home Assistant returned HTTP 404: {"message":"Entity not found."}'
    )
    plugin = HomeAssistantTelemetryPlugin(check=failing)

    first = _run(plugin)
    assert first.success is False
    assert first.health is HealthStatus.DEGRADED
    assert first.metadata["restart_grace_seconds"] == 600
    assert "may be restarting" in first.message

    clock[0] += 599
    assert _run(plugin).health is HealthStatus.DEGRADED
    clock[0] += 2
    # Still no value after the grace period: a real fault, reported critical.
    assert _run(plugin).health is None

    # A recovery resets the grace period for the next restart.
    plugin._check = FakeHomeAssistantTelemetryCheck(
        HomeAssistantTelemetryCheckResult(
            service_name="Mesure Puissance",
            healthy=True,
            primary=HomeAssistantTelemetryValue(
                entity_id="sensor.sun_01_power", value=10.5, unit="W"
            ),
        )
    )
    assert _run(plugin).success is True
    plugin._check = failing
    assert _run(plugin).health is HealthStatus.DEGRADED


def test_a_value_that_stopped_reporting_stays_critical_at_once() -> None:
    plugin = HomeAssistantTelemetryPlugin(
        check=_failing(
            12.0, "Entity sensor.sun_01_power has not reported for 900 seconds."
        )
    )
    result = _run(plugin)
    assert result.success is False
    assert result.health is None
    assert "restart_grace_seconds" not in result.metadata
