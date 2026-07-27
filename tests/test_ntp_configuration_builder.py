"""Tests for NTP runtime configuration construction."""

import pytest

from builder import NTPConfigurationBuilder
from configuration.ntp import NTPPluginConfig, NTPPolicyConfig
from infrastructure import (
    Endpoint,
    EndpointType,
    Infrastructure,
    Node,
    Service,
    ServiceType,
)


def test_ntp_configuration_builder_discovers_ntp_services() -> None:
    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[
            Node(
                name="infra-01",
                services=[
                    Service(
                        name="ntp-primary",
                        type=ServiceType.NTP,
                        endpoint=Endpoint(
                            type=EndpointType.IP,
                            address="192.168.1.10",
                            port=123,
                        ),
                    ),
                    Service(
                        name="dns-primary",
                        type=ServiceType.DNS,
                        endpoint=Endpoint(
                            type=EndpointType.IP,
                            address="192.168.1.10",
                            port=53,
                        ),
                    ),
                ],
            )
        ],
    )
    plugin_config = NTPPluginConfig(
        timeout=1.5,
        retries=0,
        policy=NTPPolicyConfig(
            maximum_offset_ms=500.0,
            maximum_stratum=10,
        ),
    )

    config = NTPConfigurationBuilder().build(infrastructure, plugin_config)

    assert len(config.servers) == 1
    assert config.servers[0].name == "ntp-primary"
    assert config.servers[0].address == "192.168.1.10"
    assert config.servers[0].port == 123
    assert config.timeout == 1.5
    assert config.retries == 0
    assert config.policy.maximum_offset_ms == 500.0
    assert config.policy.maximum_stratum == 10


def test_ntp_configuration_builder_uses_standard_port() -> None:
    service = Service(
        name="ntp-primary",
        type=ServiceType.NTP,
        endpoint=Endpoint(
            type=EndpointType.IP,
            address="192.168.1.10",
        ),
    )
    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[Node(name="infra-01", services=[service])],
    )

    config = NTPConfigurationBuilder().build(
        infrastructure,
        NTPPluginConfig(),
    )

    assert config.servers[0].port == 123


def test_ntp_configuration_builder_rejects_invalid_port() -> None:
    service = Service(
        name="ntp-primary",
        type=ServiceType.NTP,
        endpoint=Endpoint(
            type=EndpointType.IP,
            address="192.168.1.10",
            port=70_000,
        ),
    )
    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[Node(name="infra-01", services=[service])],
    )

    with pytest.raises(ValueError, match="invalid port"):
        NTPConfigurationBuilder().build(
            infrastructure,
            NTPPluginConfig(),
        )
