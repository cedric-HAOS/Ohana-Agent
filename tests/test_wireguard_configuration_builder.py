"""Tests for Freebox WireGuard runtime configuration construction."""

import pytest

from builder import WireGuardConfigurationBuilder
from configuration.wireguard import WireGuardPluginConfig
from infrastructure import (
    Endpoint,
    EndpointType,
    Infrastructure,
    Node,
    Service,
    ServiceType,
)


def test_wireguard_builder_uses_freebox_endpoint_and_metadata() -> None:
    service = Service(
        name="remote-access",
        type=ServiceType.WIREGUARD,
        endpoint=Endpoint(
            type=EndpointType.IP,
            address="192.168.1.1",
            port=443,
        ),
        metadata={
            "scheme": "https",
            "server_name": "wireguard",
        },
    )
    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[Node(name="freebox", services=[service])],
    )

    config = WireGuardConfigurationBuilder().build(
        infrastructure,
        WireGuardPluginConfig(app_token="secret"),
    )

    assert len(config.services) == 1
    assert config.services[0].name == "remote-access"
    assert config.services[0].base_url == "https://192.168.1.1:443"
    assert config.services[0].server_name == "wireguard"
    assert config.app_token == "secret"


def test_wireguard_builder_requires_freebox_endpoint() -> None:
    service = Service(
        name="remote-access",
        type=ServiceType.WIREGUARD,
    )
    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[Node(name="freebox", services=[service])],
    )

    with pytest.raises(LookupError, match="Freebox endpoint"):
        WireGuardConfigurationBuilder().build(
            infrastructure,
            WireGuardPluginConfig(),
        )
