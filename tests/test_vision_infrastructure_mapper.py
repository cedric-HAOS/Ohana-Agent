from ohana_agent.configuration.enums import (
    TopologyDeviceKind,
    TopologyLayoutKind,
    TopologyLinkDirection,
    TopologyLinkKind,
)
from ohana_agent.configuration.infrastructure import (
    InfrastructureConfig,
    InfrastructureIdentityConfig,
    InfrastructureMetadataConfig,
    NodeConfig,
    NodeEndpointConfig,
    ServiceConfig,
    TopologyConfig,
    TopologyDeviceConfig,
    TopologyGridPositionConfig,
    TopologyLayoutConfig,
    TopologyLinkConfig,
)
from ohana_agent.observation.exporters import VisionInfrastructureMapper


def build_infrastructure_config() -> InfrastructureConfig:
    """Build a stable infrastructure configuration used by mapper tests."""
    return InfrastructureConfig(
        infrastructure=InfrastructureIdentityConfig(
            id="ohana-house",
            name="Ohana House",
            environment="production",
        ),
        metadata=InfrastructureMetadataConfig(
            version="1.0",
            tags=[
                "production",
                "home",
            ],
        ),
        nodes=[
            NodeConfig(
                id="infra-01",
                name="INFRA-01",
                description=("Serveur principal de l'infrastructure Ohana"),
                endpoint=NodeEndpointConfig(
                    type="ip",
                    address="192.168.1.10",
                ),
            ),
            NodeConfig(
                id="ha-green",
                name="HA-Green",
                description="Instance Home Assistant principale",
                endpoint=NodeEndpointConfig(
                    type="ip",
                    address="192.168.1.20",
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
            ServiceConfig(
                id="mqtt-primary",
                name="MQTT principal",
                type="mqtt",
                node="ha-green",
                port=1883,
            ),
        ],
    )


def test_mapper_builds_vision_infrastructure_payload() -> None:
    mapper = VisionInfrastructureMapper()

    payload = mapper.to_payload(
        build_infrastructure_config(),
    )

    assert payload == {
        "schema_version": 1,
        "infrastructure_id": "ohana-house",
        "name": "Ohana House",
        "environment": "production",
        "metadata": {
            "version": "1.0",
            "tags": [
                "production",
                "home",
            ],
        },
        "nodes": [
            {
                "node_id": "infra-01",
                "name": "INFRA-01",
                "description": ("Serveur principal de l'infrastructure Ohana"),
                "endpoint": {
                    "type": "ip",
                    "address": "192.168.1.10",
                },
            },
            {
                "node_id": "ha-green",
                "name": "HA-Green",
                "description": ("Instance Home Assistant principale"),
                "endpoint": {
                    "type": "ip",
                    "address": "192.168.1.20",
                },
            },
        ],
        "services": [
            {
                "service_id": "dns-primary",
                "name": "DNS principal",
                "type": "dns",
                "node_id": "infra-01",
                "port": 53,
                "implementation": None,
                "enabled": True,
                "critical": False,
                "metadata": {},
            },
            {
                "service_id": "mqtt-primary",
                "name": "MQTT principal",
                "type": "mqtt",
                "node_id": "ha-green",
                "port": 1883,
                "implementation": None,
                "enabled": True,
                "critical": False,
                "metadata": {},
            },
        ],
    }


def test_mapper_supports_empty_infrastructure() -> None:
    config = InfrastructureConfig(
        infrastructure=InfrastructureIdentityConfig(
            id="empty",
            name="Empty infrastructure",
        ),
    )

    payload = VisionInfrastructureMapper().to_payload(config)

    assert payload["nodes"] == []
    assert payload["services"] == []


def test_mapper_preserves_service_without_port() -> None:
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
                    address="192.168.1.10",
                ),
            ),
        ],
        services=[
            ServiceConfig(
                id="service-without-port",
                name="Service sans port",
                type="other",
                node="infra-01",
            ),
        ],
    )

    payload = VisionInfrastructureMapper().to_payload(config)

    assert payload["services"][0]["port"] is None


def test_mapper_does_not_share_metadata_tags() -> None:
    config = build_infrastructure_config()

    payload = VisionInfrastructureMapper().to_payload(config)

    payload["metadata"]["tags"].append("modified")

    assert config.metadata.tags == [
        "production",
        "home",
    ]


def test_mapper_only_emits_public_contract_fields() -> None:
    payload = VisionInfrastructureMapper().to_payload(
        build_infrastructure_config(),
    )

    assert set(payload) == {
        "schema_version",
        "infrastructure_id",
        "name",
        "environment",
        "metadata",
        "nodes",
        "services",
    }

    assert set(payload["nodes"][0]) == {
        "node_id",
        "name",
        "description",
        "endpoint",
    }

    assert set(payload["services"][0]) == {
        "service_id",
        "name",
        "type",
        "node_id",
        "port",
        "implementation",
        "enabled",
        "critical",
        "metadata",
    }


def build_topology_config() -> InfrastructureConfig:
    """Build an infrastructure configuration with a complete topology."""
    config = build_infrastructure_config()

    return config.model_copy(
        update={
            "topology": TopologyConfig(
                devices=[
                    TopologyDeviceConfig(
                        id="internet",
                        label="Internet",
                        kind=TopologyDeviceKind.INTERNET,
                    ),
                    TopologyDeviceConfig(
                        id="infra-01-device",
                        label="INFRA-01",
                        kind=TopologyDeviceKind.RASPBERRY_PI,
                        node="infra-01",
                        metadata={
                            "role": "infrastructure_server",
                        },
                    ),
                ],
                links=[
                    TopologyLinkConfig(
                        id="internet-infra-01",
                        source="internet",
                        target="infra-01-device",
                        kind=TopologyLinkKind.ETHERNET,
                        direction=(TopologyLinkDirection.BIDIRECTIONAL),
                        label="Ethernet 1 Gb",
                        bandwidth_mbps=1000,
                    ),
                ],
                layouts=[
                    TopologyLayoutConfig(
                        id="physical",
                        label="Topologie physique",
                        kind=TopologyLayoutKind.PHYSICAL,
                        positions={
                            "internet": TopologyGridPositionConfig(
                                column=0,
                                row=1,
                            ),
                            "infra-01-device": (
                                TopologyGridPositionConfig(
                                    column=2,
                                    row=1,
                                )
                            ),
                        },
                    ),
                ],
                metadata={
                    "description": "Physical topology",
                },
            ),
        }
    )


def test_mapper_emits_complete_topology() -> None:
    payload = VisionInfrastructureMapper().to_payload(
        build_topology_config(),
    )

    assert payload["topology"] == {
        "devices": [
            {
                "device_id": "internet",
                "label": "Internet",
                "kind": "internet",
                "node_id": None,
                "address": None,
                "metadata": {},
            },
            {
                "device_id": "infra-01-device",
                "label": "INFRA-01",
                "kind": "raspberry_pi",
                "node_id": "infra-01",
                "address": "192.168.1.10",
                "metadata": {
                    "role": "infrastructure_server",
                },
            },
        ],
        "links": [
            {
                "link_id": "internet-infra-01",
                "source_device_id": "internet",
                "target_device_id": "infra-01-device",
                "kind": "ethernet",
                "direction": "bidirectional",
                "label": "Ethernet 1 Gb",
                "bandwidth_mbps": 1000.0,
                "metadata": {},
            },
        ],
        "layouts": [
            {
                "layout_id": "physical",
                "label": "Topologie physique",
                "kind": "physical",
                "positions": {
                    "internet": {
                        "column": 0,
                        "row": 1,
                    },
                    "infra-01-device": {
                        "column": 2,
                        "row": 1,
                    },
                },
                "metadata": {},
            },
        ],
        "metadata": {
            "description": "Physical topology",
        },
    }


def test_mapper_omits_topology_when_not_configured() -> None:
    payload = VisionInfrastructureMapper().to_payload(
        build_infrastructure_config(),
    )

    assert "topology" not in payload


def test_mapper_does_not_share_topology_metadata() -> None:
    config = build_topology_config()

    payload = VisionInfrastructureMapper().to_payload(config)
    payload["topology"]["metadata"]["modified"] = True
    payload["topology"]["devices"][1]["metadata"]["modified"] = True

    assert config.topology is not None
    assert "modified" not in config.topology.metadata
    assert "modified" not in config.topology.devices[1].metadata
