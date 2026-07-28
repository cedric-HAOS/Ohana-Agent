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


def test_zwave_builder_discovers_websocket_service() -> None:
    service = Service(
        name="zwave-main",
        type=ServiceType.ZWAVE,
        endpoint=Endpoint(
            type=EndpointType.IP,
            address="192.168.1.11",
            port=3000,
        ),
        metadata={
            "scheme": "wss",
            "websocket_path": "/zjs",
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
    assert config.services[0].url == "wss://192.168.1.11:3000/zjs"
    assert config.timeout == 2.5
    assert config.retries == 0
    assert config.verify_tls is False


def test_zwave_builder_uses_home_assistant_defaults() -> None:
    service = Service(
        name="zwave-main",
        type=ServiceType.ZWAVE,
        endpoint=Endpoint(
            type=EndpointType.IP,
            address="192.168.1.11",
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

    assert config.services[0].url == "ws://192.168.1.11:3000"


def test_zwave_builder_keeps_legacy_http_health_endpoint() -> None:
    service = Service(
        name="zwave-main",
        type=ServiceType.ZWAVE,
        endpoint=Endpoint(
            type=EndpointType.IP,
            address="192.168.1.11",
            port=8091,
        ),
        metadata={
            "scheme": "http",
            "health_path": "/health/zwave",
        },
    )
    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[Node(name="rpi-zwave", services=[service])],
    )

    config = ZWaveConfigurationBuilder().build(
        infrastructure,
        ZWavePluginConfig(),
    )

    assert config.services[0].url == "http://192.168.1.11:8091/health/zwave"
