"""Tests for Z-Wave runtime configuration construction."""

from builder import ZWaveConfigurationBuilder
from configuration.zwave import ZWavePluginConfig
from infrastructure import (
    Endpoint,
    EndpointType,
    Infrastructure,
    Node,
    Service,
    ServiceType,
)


def test_zwave_builder_discovers_services_and_builds_health_url() -> None:
    service = Service(
        name="zwave-main",
        type=ServiceType.ZWAVE,
        endpoint=Endpoint(
            type=EndpointType.IP,
            address="192.168.1.54",
            port=8091,
        ),
        metadata={
            "scheme": "https",
            "health_path": "/health/zwave",
        },
    )
    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[Node(name="rpi-zwave", services=[service])],
    )

    config = ZWaveConfigurationBuilder().build(
        infrastructure,
        ZWavePluginConfig(timeout=2.5, retries=0, verify_tls=False),
    )

    assert len(config.services) == 1
    assert config.services[0].url == ("https://192.168.1.54:8091/health/zwave")
    assert config.timeout == 2.5
    assert config.retries == 0
    assert config.verify_tls is False


def test_zwave_builder_uses_default_port_and_path() -> None:
    service = Service(
        name="zwave-main",
        type=ServiceType.ZWAVE,
        endpoint=Endpoint(
            type=EndpointType.IP,
            address="192.168.1.54",
        ),
    )
    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[Node(name="rpi-zwave", services=[service])],
    )

    config = ZWaveConfigurationBuilder().build(
        infrastructure,
        ZWavePluginConfig(),
    )

    assert config.services[0].url == ("http://192.168.1.54:8091/health/zwave")
