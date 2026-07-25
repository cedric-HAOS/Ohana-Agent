import pytest

from builder import DNSConfigurationBuilder, InfrastructureBuilder
from configuration.dns import (
    DNSPluginConfig,
)
from configuration.dns import (
    DNSPolicyConfig as DeclarativeDNSPolicyConfig,
)
from infrastructure import (
    Endpoint,
    EndpointType,
    Infrastructure,
    Node,
    Service,
    ServiceType,
)
from loader import DNSConfigLoader, InfrastructureLoader


def build_dns_infrastructure(
    *,
    service_type: ServiceType = ServiceType.DNS,
    include_endpoint: bool = True,
    service_enabled: bool = True,
    endpoint_enabled: bool = True,
) -> Infrastructure:
    """Build infrastructure used by DNS configuration tests."""
    endpoint = (
        Endpoint(
            type=EndpointType.IP,
            address="192.168.1.11",
            port=53,
            enabled=endpoint_enabled,
        )
        if include_endpoint
        else None
    )

    service = Service(
        name="dns-primary",
        type=service_type,
        endpoint=endpoint,
        enabled=service_enabled,
    )

    node = Node(
        name="zwave-01",
        services=[service],
    )

    return Infrastructure(
        name="Ohana House",
        nodes=[node],
    )


def test_dns_configuration_builder_resolves_infrastructure_service() -> None:
    infrastructure = build_dns_infrastructure()
    declarative_config = DNSPluginConfig(
        services=["dns-primary"],
        queries=["example.com"],
    )

    builder = DNSConfigurationBuilder()

    config = builder.build(
        infrastructure,
        declarative_config,
    )

    assert len(config.servers) == 1
    assert config.servers[0].name == "dns-primary"
    assert config.servers[0].address == "192.168.1.11"
    assert config.servers[0].enabled is True
    assert config.queries == ["example.com"]


def test_dns_configuration_builder_copies_plugin_settings() -> None:
    infrastructure = build_dns_infrastructure()
    declarative_config = DNSPluginConfig(
        services=["dns-primary"],
        queries=[
            "example.com",
            "openai.com",
        ],
        timeout=1.5,
        retries=2,
        policy=DeclarativeDNSPolicyConfig(
            minimum_healthy_servers=2,
        ),
    )

    config = DNSConfigurationBuilder().build(
        infrastructure,
        declarative_config,
    )

    assert config.queries == [
        "example.com",
        "openai.com",
    ]
    assert config.timeout == 1.5
    assert config.retries == 2
    assert config.policy.minimum_healthy_servers == 2


def test_dns_configuration_builder_ignores_legacy_service_filter() -> None:
    infrastructure = build_dns_infrastructure()
    declarative_config = DNSPluginConfig(
        services=["dns-secondary"],
    )

    config = DNSConfigurationBuilder().build(
        infrastructure,
        declarative_config,
    )

    assert [server.name for server in config.servers] == ["dns-primary"]


def test_dns_configuration_builder_ignores_non_dns_services() -> None:
    infrastructure = build_dns_infrastructure(
        service_type=ServiceType.MQTT,
    )
    declarative_config = DNSPluginConfig(
        services=["dns-primary"],
    )

    config = DNSConfigurationBuilder().build(
        infrastructure,
        declarative_config,
    )

    assert config.servers == []


def test_dns_configuration_builder_discovers_all_dns_services() -> None:
    infrastructure = build_dns_infrastructure()
    secondary = Service(
        name="dns-secondary",
        type=ServiceType.DNS,
        endpoint=Endpoint(
            type=EndpointType.IP,
            address="192.168.1.12",
            port=53,
        ),
    )
    infrastructure.nodes[0].services.append(secondary)

    config = DNSConfigurationBuilder().build(
        infrastructure,
        DNSPluginConfig(),
    )

    assert [server.name for server in config.servers] == [
        "dns-primary",
        "dns-secondary",
    ]
    assert [server.address for server in config.servers] == [
        "192.168.1.11",
        "192.168.1.12",
    ]


def test_dns_configuration_builder_rejects_service_without_endpoint() -> None:
    infrastructure = build_dns_infrastructure(
        include_endpoint=False,
    )
    declarative_config = DNSPluginConfig(
        services=["dns-primary"],
    )

    with pytest.raises(
        LookupError,
        match="has no endpoint",
    ):
        DNSConfigurationBuilder().build(
            infrastructure,
            declarative_config,
        )


@pytest.mark.parametrize(
    ("service_enabled", "endpoint_enabled"),
    [
        (False, True),
        (True, False),
        (False, False),
    ],
)
def test_dns_configuration_builder_disables_unavailable_server(
    service_enabled: bool,
    endpoint_enabled: bool,
) -> None:
    infrastructure = build_dns_infrastructure(
        service_enabled=service_enabled,
        endpoint_enabled=endpoint_enabled,
    )
    declarative_config = DNSPluginConfig(
        services=["dns-primary"],
    )

    config = DNSConfigurationBuilder().build(
        infrastructure,
        declarative_config,
    )

    assert config.servers[0].enabled is False


def test_dns_configuration_builder_uses_real_yaml_files() -> None:
    infrastructure_config = InfrastructureLoader().load("config/infrastructure.yaml")
    infrastructure = InfrastructureBuilder().build(infrastructure_config)

    dns_plugin_config = DNSConfigLoader().load("config/plugins/dns.yaml")

    dns_config = DNSConfigurationBuilder().build(
        infrastructure,
        dns_plugin_config,
    )

    assert len(dns_config.servers) == 1
    assert dns_config.servers[0].name == "dns-primary"
    assert dns_config.servers[0].address == "192.168.1.10"
    assert dns_config.servers[0].enabled is True
    assert dns_config.queries == [
        "example.com",
    ]
