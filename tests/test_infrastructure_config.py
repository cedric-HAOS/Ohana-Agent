from ohana_agent.configuration.infrastructure import (
    InfrastructureConfig,
    InfrastructureIdentityConfig,
    InfrastructureMetadataConfig,
    NodeConfig,
    NodeEndpointConfig,
    ServiceConfig,
)


def test_infrastructure_identity_config_can_be_created() -> None:
    config = InfrastructureIdentityConfig(
        id="ohana-house",
        name="Ohana House",
    )

    assert config.id == "ohana-house"
    assert config.name == "Ohana House"
    assert config.environment == "production"


def test_infrastructure_metadata_config_has_defaults() -> None:
    config = InfrastructureMetadataConfig()

    assert config.version == "1.0"
    assert config.tags == []


def test_node_endpoint_config_can_be_created() -> None:
    config = NodeEndpointConfig(
        type="ip",
        address="192.168.1.54",
    )

    assert config.type == "ip"
    assert config.address == "192.168.1.54"


def test_node_config_can_be_created() -> None:
    config = NodeConfig(
        id="infra-01",
        name="INFRA-01",
        description="Serveur infrastructure principal",
        endpoint=NodeEndpointConfig(
            type="ip",
            address="192.168.1.54",
        ),
    )

    assert config.id == "infra-01"
    assert config.name == "INFRA-01"
    assert config.description == "Serveur infrastructure principal"
    assert config.endpoint.address == "192.168.1.54"


def test_service_config_can_be_created() -> None:
    config = ServiceConfig(
        id="dns-primary",
        name="DNS principal",
        type="dns",
        node="infra-01",
        port=53,
    )

    assert config.id == "dns-primary"
    assert config.name == "DNS principal"
    assert config.type == "dns"
    assert config.node == "infra-01"
    assert config.port == 53


def test_infrastructure_config_can_be_created() -> None:
    config = InfrastructureConfig(
        infrastructure=InfrastructureIdentityConfig(
            id="ohana-house",
            name="Ohana House",
        ),
        nodes=[
            NodeConfig(
                id="infra-01",
                name="INFRA-01",
                endpoint=NodeEndpointConfig(
                    type="ip",
                    address="192.168.1.54",
                ),
            ),
        ],
        services=[
            ServiceConfig(
                id="dns-primary",
                name="DNS principal",
                type="dns",
                node="infra-01",
                port=53,
            ),
        ],
    )

    assert config.infrastructure.id == "ohana-house"
    assert len(config.nodes) == 1
    assert len(config.services) == 1
