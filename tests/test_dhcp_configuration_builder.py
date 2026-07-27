from pathlib import Path

import pytest

from builder.dhcp_configuration_builder import DHCPConfigurationBuilder
from configuration.dhcp import DHCPPluginConfig, DHCPPolicyConfig
from infrastructure import (
    Endpoint,
    EndpointType,
    Infrastructure,
    Node,
    Service,
    ServiceType,
)


def build_infrastructure(
    *,
    port: int | None = 67,
    enabled: bool = True,
) -> Infrastructure:
    node = Node(name="infra-01")
    node.add_endpoint(
        Endpoint(
            type=EndpointType.IP,
            address="192.168.1.10",
        )
    )
    node.add_service(
        Service(
            name="dhcp-primary",
            type=ServiceType.DHCP,
            endpoint=Endpoint(
                type=EndpointType.IP,
                address="192.168.1.10",
                port=port,
            ),
            enabled=enabled,
        )
    )
    return Infrastructure(name="ohana-house", nodes=[node])


def test_dhcp_configuration_builder_discovers_service() -> None:
    config = DHCPPluginConfig(
        check_service_active=False,
        timeout=1.5,
        policy=DHCPPolicyConfig(maximum_pool_usage_percent=75),
    )

    runtime = DHCPConfigurationBuilder().build(
        build_infrastructure(),
        config,
        server_node_id="infra-01",
        main_config_path=Path("/tmp/dnsmasq.conf"),
        leases_path=Path("/tmp/dnsmasq.leases"),
    )

    assert len(runtime.servers) == 1
    assert runtime.servers[0].name == "dhcp-primary"
    assert runtime.servers[0].address == "192.168.1.10"
    assert runtime.servers[0].port == 67
    assert runtime.servers[0].enabled is True
    assert runtime.main_config_path == Path("/tmp/dnsmasq.conf")
    assert runtime.leases_path == Path("/tmp/dnsmasq.leases")
    assert runtime.service_status_command is None
    assert runtime.timeout == 1.5
    assert runtime.policy.maximum_pool_usage_percent == 75


def test_dhcp_configuration_builder_uses_default_port() -> None:
    runtime = DHCPConfigurationBuilder().build(
        build_infrastructure(port=None),
        DHCPPluginConfig(),
        server_node_id="infra-01",
        main_config_path=Path("/tmp/dnsmasq.conf"),
        leases_path=Path("/tmp/dnsmasq.leases"),
    )

    assert runtime.servers[0].port == 67


def test_dhcp_configuration_builder_preserves_disabled_service() -> None:
    runtime = DHCPConfigurationBuilder().build(
        build_infrastructure(enabled=False),
        DHCPPluginConfig(),
        server_node_id="infra-01",
        main_config_path=Path("/tmp/dnsmasq.conf"),
        leases_path=Path("/tmp/dnsmasq.leases"),
    )

    assert runtime.servers[0].enabled is False


def test_dhcp_configuration_builder_rejects_service_without_endpoint() -> None:
    node = Node(name="infra-01")
    node.add_service(
        Service(
            name="dhcp-primary",
            type=ServiceType.DHCP,
        )
    )
    infrastructure = Infrastructure(name="ohana-house", nodes=[node])

    with pytest.raises(LookupError, match="has no endpoint"):
        DHCPConfigurationBuilder().build(
            infrastructure,
            DHCPPluginConfig(),
            server_node_id="infra-01",
            main_config_path=Path("/tmp/dnsmasq.conf"),
            leases_path=Path("/tmp/dnsmasq.leases"),
        )


def test_dhcp_configuration_builder_rejects_unknown_server_node() -> None:
    with pytest.raises(LookupError, match="server node not found"):
        DHCPConfigurationBuilder().build(
            build_infrastructure(),
            DHCPPluginConfig(),
            server_node_id="missing-node",
            main_config_path=Path("/tmp/dnsmasq.conf"),
            leases_path=Path("/tmp/dnsmasq.leases"),
        )
