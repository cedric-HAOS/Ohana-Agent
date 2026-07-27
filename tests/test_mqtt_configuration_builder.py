"""Tests for MQTT runtime configuration construction."""

import pytest

from builder import MQTTConfigurationBuilder
from configuration.mqtt_plugin import MQTTPluginConfig
from infrastructure import (
    Endpoint,
    EndpointType,
    Infrastructure,
    Node,
    Service,
    ServiceType,
)


def make_infrastructure(port: int | None = 1883) -> Infrastructure:
    return Infrastructure(
        name="Ohana",
        nodes=[
            Node(
                name="ha-01",
                services=[
                    Service(
                        name="mqtt-primary",
                        type=ServiceType.MQTT,
                        endpoint=Endpoint(
                            type=EndpointType.IP,
                            address="192.168.1.247",
                            port=port,
                        ),
                    ),
                    Service(
                        name="http",
                        type=ServiceType.HTTP,
                        endpoint=Endpoint(
                            type=EndpointType.IP,
                            address="192.168.1.247",
                            port=8123,
                        ),
                    ),
                ],
            )
        ],
    )


def test_mqtt_configuration_builder_discovers_mqtt_services() -> None:
    plugin_config = MQTTPluginConfig.model_validate(
        {
            "timeout": 3.0,
            "retries": 0,
            "qos": 2,
            "authentication": {
                "username": "observer",
                "password": "secret",
            },
        }
    )

    config = MQTTConfigurationBuilder().build(
        make_infrastructure(),
        plugin_config,
    )

    assert len(config.brokers) == 1
    assert config.brokers[0].name == "mqtt-primary"
    assert config.brokers[0].address == "192.168.1.247"
    assert config.brokers[0].port == 1883
    assert config.timeout == 3.0
    assert config.retries == 0
    assert config.qos == 2
    assert config.authentication.username == "observer"
    assert config.authentication.password == "secret"


def test_mqtt_configuration_builder_uses_tls_default_port() -> None:
    config = MQTTConfigurationBuilder().build(
        make_infrastructure(port=None),
        MQTTPluginConfig.model_validate({"tls": {"enabled": True}}),
    )

    assert config.brokers[0].port == 8883


def test_mqtt_configuration_builder_rejects_invalid_port() -> None:
    with pytest.raises(ValueError, match="invalid port"):
        MQTTConfigurationBuilder().build(
            make_infrastructure(port=70_000),
            MQTTPluginConfig(),
        )
