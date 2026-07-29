"""Tests for Téléinformation runtime configuration construction."""

import pytest

from builder import InfrastructureBuilder, TeleinformationConfigurationBuilder
from configuration.infrastructure import InfrastructureConfig
from configuration.teleinformation import TeleinformationPluginConfig


def infrastructure_with_teleinformation_service(
    *,
    include_power_entity: bool = True,
) -> InfrastructureConfig:
    metadata: dict[str, object] = {
        "tariff_entity_id": "sensor.teleinfo_041964385922_ntarf",
        "blue_off_peak_entity_id": "sensor.teleinfo_041964385922_easf01",
        "blue_peak_entity_id": "sensor.teleinfo_041964385922_easf02",
        "white_off_peak_entity_id": "sensor.teleinfo_041964385922_easf03",
        "white_peak_entity_id": "sensor.teleinfo_041964385922_easf04",
        "red_off_peak_entity_id": "sensor.teleinfo_041964385922_easf05",
        "red_peak_entity_id": "sensor.teleinfo_041964385922_easf06",
        "maximum_age_seconds": 180,
    }

    if include_power_entity:
        metadata["apparent_power_entity_id"] = "sensor.teleinfo_041964385922_sinsts"

    return InfrastructureConfig.model_validate(
        {
            "infrastructure": {
                "id": "ohana-house",
                "name": "Ohana House",
            },
            "nodes": [
                {
                    "id": "linky-01",
                    "name": "RPI-Linky",
                    "endpoint": {
                        "type": "ip",
                        "address": "192.168.1.53",
                    },
                }
            ],
            "services": [
                {
                    "id": "teleinformation",
                    "name": "Téléinformation Linky",
                    "type": "teleinformation",
                    "node": "linky-01",
                    "implementation": "teleinfo2mqtt",
                    "enabled": True,
                    "metadata": metadata,
                }
            ],
        }
    )


def plugin_config() -> TeleinformationPluginConfig:
    return TeleinformationPluginConfig(
        access_token="secret",
        access_token_environment_variable=None,
    )


def test_teleinformation_builder_discovers_linky_service() -> None:
    runtime = TeleinformationConfigurationBuilder().build(
        InfrastructureBuilder().build(infrastructure_with_teleinformation_service()),
        plugin_config(),
    )

    assert len(runtime.services) == 1
    service = runtime.services[0]
    assert service.name == "teleinformation"
    assert service.label == "Téléinformation Linky"
    assert service.node_id == "linky-01"
    assert service.apparent_power_entity_id.endswith("_sinsts")
    assert service.tariff_entity_id.endswith("_ntarf")
    assert service.index_entity_ids["red_peak"].endswith("_easf06")
    assert service.maximum_age_seconds == 180


def test_teleinformation_builder_requires_apparent_power_entity() -> None:
    with pytest.raises(ValueError, match="apparent_power_entity_id"):
        TeleinformationConfigurationBuilder().build(
            InfrastructureBuilder().build(
                infrastructure_with_teleinformation_service(
                    include_power_entity=False,
                )
            ),
            plugin_config(),
        )
