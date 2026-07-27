"""Tests for network presence target discovery."""

from builder import NetworkConfigurationBuilder
from configuration.infrastructure import InfrastructureConfig
from configuration.network import NetworkPluginConfig


def test_network_configuration_builder_discovers_addressable_devices() -> None:
    infrastructure = InfrastructureConfig.model_validate(
        {
            "infrastructure": {
                "id": "ohana-house",
                "name": "Ohana House",
            },
            "nodes": [
                {
                    "id": "infra-01",
                    "name": "INFRA-01",
                    "endpoint": {
                        "type": "ip",
                        "address": "192.168.1.10",
                    },
                }
            ],
            "topology": {
                "devices": [
                    {
                        "id": "freebox",
                        "label": "Freebox",
                        "kind": "router",
                        "address": "192.168.1.1",
                    },
                    {
                        "id": "infra-01",
                        "label": "INFRA-01",
                        "kind": "raspberry_pi",
                        "node": "infra-01",
                    },
                    {
                        "id": "camera-disabled",
                        "label": "Camera disabled",
                        "kind": "camera",
                        "address": "192.168.1.50",
                        "metadata": {
                            "network_presence_enabled": False,
                        },
                    },
                    {
                        "id": "sw-01",
                        "label": "SW-01",
                        "kind": "switch",
                    },
                ]
            },
        }
    )

    config = NetworkConfigurationBuilder().build(
        infrastructure,
        NetworkPluginConfig(
            timeout=1.5,
            retries=1,
            failure_threshold=4,
        ),
    )

    assert [(device.name, device.address) for device in config.devices] == [
        ("freebox", "192.168.1.1"),
        ("infra-01", "192.168.1.10"),
        ("camera-disabled", "192.168.1.50"),
    ]
    assert config.devices[0].enabled is True
    assert config.devices[1].node_id == "infra-01"
    assert config.devices[1].enabled is True
    assert config.devices[2].enabled is False
    assert config.timeout == 1.5
    assert config.retries == 1
    assert config.failure_threshold == 4


def test_network_configuration_builder_handles_missing_topology() -> None:
    infrastructure = InfrastructureConfig.model_validate(
        {
            "infrastructure": {
                "id": "ohana-house",
                "name": "Ohana House",
            }
        }
    )

    config = NetworkConfigurationBuilder().build(
        infrastructure,
        NetworkPluginConfig(),
    )

    assert config.devices == []
