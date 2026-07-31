"""Tests for Home Assistant telemetry runtime configuration construction."""

import pytest

from builder import HomeAssistantTelemetryConfigurationBuilder, InfrastructureBuilder
from configuration.home_assistant_telemetry import HomeAssistantTelemetryPluginConfig
from configuration.infrastructure import InfrastructureConfig


def infrastructure_with_telemetry_service(
    *,
    enabled: bool = True,
    include_primary_entity: bool = True,
    legacy: bool = False,
) -> InfrastructureConfig:
    metadata: dict[str, object] = {
        ("energy_entity_id" if legacy else "secondary_entity_id"): (
            "sensor.kitchen_energy"
        ),
        "maximum_age_seconds": 600,
    }
    if include_primary_entity:
        metadata["power_entity_id" if legacy else "primary_entity_id"] = (
            "sensor.kitchen_power"
        )

    return InfrastructureConfig.model_validate(
        {
            "infrastructure": {"id": "ohana-house", "name": "Ohana House"},
            "nodes": [
                {
                    "id": "device-kitchen",
                    "name": "Équipement cuisine",
                    "endpoint": {"type": "hostname", "address": "she-01.ohana.lan"},
                }
            ],
            "services": [
                {
                    "id": "telemetry-kitchen",
                    "name": "Télémétrie cuisine",
                    "type": (
                        "shelly_telemetry" if legacy else "home_assistant_telemetry"
                    ),
                    "node": "device-kitchen",
                    "implementation": "Home Assistant",
                    "enabled": enabled,
                    "critical": True,
                    "metadata": metadata,
                }
            ],
        }
    )


def build_runtime(config: InfrastructureConfig):
    return InfrastructureBuilder().build(config)


def plugin_config() -> HomeAssistantTelemetryPluginConfig:
    return HomeAssistantTelemetryPluginConfig(
        access_token="secret",
        access_token_environment_variable=None,
    )


def test_home_assistant_telemetry_builder_discovers_declared_service() -> None:
    runtime = HomeAssistantTelemetryConfigurationBuilder().build(
        build_runtime(infrastructure_with_telemetry_service()),
        plugin_config(),
    )

    assert runtime.access_token == "secret"
    assert len(runtime.services) == 1
    assert runtime.services[0].name == "telemetry-kitchen"
    assert runtime.services[0].label == "Télémétrie cuisine"
    assert runtime.services[0].node_id == "device-kitchen"
    assert runtime.services[0].primary_entity_id == "sensor.kitchen_power"
    assert runtime.services[0].secondary_entity_id == "sensor.kitchen_energy"
    assert runtime.services[0].maximum_age_seconds == 600


def test_builder_accepts_legacy_shelly_service_and_metadata() -> None:
    runtime = HomeAssistantTelemetryConfigurationBuilder().build(
        build_runtime(infrastructure_with_telemetry_service(legacy=True)),
        plugin_config(),
    )

    assert len(runtime.services) == 1
    assert runtime.services[0].primary_entity_id == "sensor.kitchen_power"
    assert runtime.services[0].secondary_entity_id == "sensor.kitchen_energy"


def test_home_assistant_telemetry_builder_keeps_disabled_service_unscheduled() -> None:
    runtime = HomeAssistantTelemetryConfigurationBuilder().build(
        build_runtime(infrastructure_with_telemetry_service(enabled=False)),
        plugin_config(),
    )
    assert runtime.services[0].enabled is False


def test_home_assistant_telemetry_builder_requires_primary_entity() -> None:
    with pytest.raises(ValueError, match="primary_entity_id"):
        HomeAssistantTelemetryConfigurationBuilder().build(
            build_runtime(
                infrastructure_with_telemetry_service(include_primary_entity=False)
            ),
            plugin_config(),
        )
