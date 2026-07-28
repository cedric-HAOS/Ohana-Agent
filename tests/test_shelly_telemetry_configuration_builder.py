"""Tests for Shelly telemetry runtime configuration construction."""

import pytest

from builder import InfrastructureBuilder, ShellyTelemetryConfigurationBuilder
from configuration.infrastructure import InfrastructureConfig
from configuration.shelly_telemetry import ShellyTelemetryPluginConfig


def infrastructure_with_shelly_service(
    *,
    enabled: bool = True,
    include_power_entity: bool = True,
) -> InfrastructureConfig:
    metadata: dict[str, object] = {
        "energy_entity_id": "sensor.shelly_cuisine_energy",
        "maximum_age_seconds": 600,
    }

    if include_power_entity:
        metadata["power_entity_id"] = "sensor.shelly_cuisine_power"

    return InfrastructureConfig.model_validate(
        {
            "infrastructure": {
                "id": "ohana-house",
                "name": "Ohana House",
            },
            "nodes": [
                {
                    "id": "shelly-cuisine",
                    "name": "Shelly cuisine",
                    "endpoint": {
                        "type": "ip",
                        "address": "192.168.1.40",
                    },
                }
            ],
            "services": [
                {
                    "id": "shelly-telemetry-cuisine",
                    "name": "Télémétrie Shelly cuisine",
                    "type": "shelly_telemetry",
                    "node": "shelly-cuisine",
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


def plugin_config() -> ShellyTelemetryPluginConfig:
    return ShellyTelemetryPluginConfig(
        access_token="secret",
        access_token_environment_variable=None,
    )


def test_shelly_telemetry_builder_discovers_declared_service() -> None:
    runtime = ShellyTelemetryConfigurationBuilder().build(
        build_runtime(infrastructure_with_shelly_service()),
        plugin_config(),
    )

    assert runtime.access_token == "secret"
    assert len(runtime.services) == 1
    assert runtime.services[0].name == "shelly-telemetry-cuisine"
    assert runtime.services[0].label == "Télémétrie Shelly cuisine"
    assert runtime.services[0].node_id == "shelly-cuisine"
    assert runtime.services[0].energy_entity_id == ("sensor.shelly_cuisine_energy")
    assert runtime.services[0].maximum_age_seconds == 600


def test_shelly_telemetry_builder_keeps_disabled_service_unscheduled() -> None:
    runtime = ShellyTelemetryConfigurationBuilder().build(
        build_runtime(infrastructure_with_shelly_service(enabled=False)),
        plugin_config(),
    )

    assert len(runtime.services) == 1
    assert runtime.services[0].enabled is False


def test_shelly_telemetry_builder_requires_power_entity() -> None:
    with pytest.raises(ValueError, match="power_entity_id"):
        ShellyTelemetryConfigurationBuilder().build(
            build_runtime(
                infrastructure_with_shelly_service(include_power_entity=False)
            ),
            plugin_config(),
        )
