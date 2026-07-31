import pytest

from configuration.enums import (
    TopologyDeviceKind,
    TopologyLayoutKind,
    TopologyLinkKind,
)
from configuration.infrastructure import (
    InfrastructureConfig,
    InfrastructureIdentityConfig,
    NodeConfig,
    NodeEndpointConfig,
    ServiceConfig,
    TopologyConfig,
    TopologyDeviceConfig,
    TopologyGridPositionConfig,
    TopologyLayoutConfig,
    TopologyLinkConfig,
)
from configuration.infrastructure_validator import (
    InfrastructureValidationError,
    InfrastructureValidator,
)


def build_valid_config() -> InfrastructureConfig:
    return InfrastructureConfig(
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


def test_validator_accepts_valid_config() -> None:
    InfrastructureValidator().validate(build_valid_config())


def test_validator_rejects_duplicate_node_ids() -> None:
    config = InfrastructureConfig(
        infrastructure=InfrastructureIdentityConfig(
            id="ohana-house",
            name="Ohana House",
        ),
        nodes=[
            NodeConfig(
                id="infra-01",
                name="INFRA-01",
                endpoint=NodeEndpointConfig(type="ip", address="192.168.1.54"),
            ),
            NodeConfig(
                id="infra-01",
                name="Duplicate",
                endpoint=NodeEndpointConfig(type="ip", address="192.168.1.55"),
            ),
        ],
    )

    with pytest.raises(InfrastructureValidationError):
        InfrastructureValidator().validate(config)


def test_validator_rejects_duplicate_service_ids() -> None:
    config = build_valid_config()
    config.services.append(
        ServiceConfig(
            id="dns-primary",
            name="DNS duplicate",
            type="dns",
            node="infra-01",
            port=54,
        )
    )

    with pytest.raises(InfrastructureValidationError):
        InfrastructureValidator().validate(config)


def test_validator_rejects_invalid_node_endpoint_type() -> None:
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
                    type="tcp",
                    address="192.168.1.54",
                ),
            ),
        ],
    )

    with pytest.raises(InfrastructureValidationError):
        InfrastructureValidator().validate(config)


def test_validator_rejects_invalid_node_address() -> None:
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
                    address="not-an-ip",
                ),
            ),
        ],
    )

    with pytest.raises(InfrastructureValidationError):
        InfrastructureValidator().validate(config)


def test_validator_rejects_service_referencing_unknown_node() -> None:
    config = InfrastructureConfig(
        infrastructure=InfrastructureIdentityConfig(
            id="ohana-house",
            name="Ohana House",
        ),
        nodes=[
            NodeConfig(
                id="infra-01",
                name="INFRA-01",
                endpoint=NodeEndpointConfig(type="ip", address="192.168.1.54"),
            ),
        ],
        services=[
            ServiceConfig(
                id="dns-primary",
                name="DNS principal",
                type="dns",
                node="unknown-node",
                port=53,
            ),
        ],
    )

    with pytest.raises(InfrastructureValidationError):
        InfrastructureValidator().validate(config)


def test_validator_rejects_port_below_range() -> None:
    config = build_valid_config()
    config.services.append(
        ServiceConfig(
            id="bad-service",
            name="Bad service",
            type="dns",
            node="infra-01",
            port=0,
        )
    )

    with pytest.raises(InfrastructureValidationError):
        InfrastructureValidator().validate(config)


def test_validator_rejects_port_above_range() -> None:
    config = build_valid_config()
    config.services.append(
        ServiceConfig(
            id="bad-service",
            name="Bad service",
            type="dns",
            node="infra-01",
            port=65536,
        )
    )

    with pytest.raises(InfrastructureValidationError):
        InfrastructureValidator().validate(config)


def build_valid_topology_config() -> InfrastructureConfig:
    config = build_valid_config()

    return config.model_copy(
        update={
            "topology": TopologyConfig(
                devices=[
                    TopologyDeviceConfig(
                        id="router",
                        label="Router",
                        kind=TopologyDeviceKind.ROUTER,
                    ),
                    TopologyDeviceConfig(
                        id="infra",
                        label="INFRA-01",
                        kind=TopologyDeviceKind.RASPBERRY_PI,
                        node="infra-01",
                    ),
                ],
                links=[
                    TopologyLinkConfig(
                        id="router-infra",
                        source="router",
                        target="infra",
                        kind=TopologyLinkKind.ETHERNET,
                    ),
                ],
                layouts=[
                    TopologyLayoutConfig(
                        id="physical",
                        label="Physical",
                        kind=TopologyLayoutKind.PHYSICAL,
                        positions={
                            "router": TopologyGridPositionConfig(
                                column=0,
                                row=0,
                            ),
                            "infra": TopologyGridPositionConfig(
                                column=1,
                                row=0,
                            ),
                        },
                    ),
                ],
            ),
        }
    )


def test_validator_accepts_valid_topology() -> None:
    InfrastructureValidator().validate(build_valid_topology_config())


def test_validator_rejects_duplicate_topology_device_ids() -> None:
    config = build_valid_topology_config()
    assert config.topology is not None
    config.topology.devices.append(
        TopologyDeviceConfig(
            id="router",
            label="Duplicate",
            kind=TopologyDeviceKind.ROUTER,
        )
    )

    with pytest.raises(
        InfrastructureValidationError,
        match="Topology device identifiers must be unique",
    ):
        InfrastructureValidator().validate(config)


def test_validator_rejects_unknown_topology_node() -> None:
    config = build_valid_topology_config()
    assert config.topology is not None
    config.topology.devices.append(
        TopologyDeviceConfig(
            id="missing",
            label="Missing",
            kind=TopologyDeviceKind.SERVER,
            node="missing-node",
        )
    )

    with pytest.raises(
        InfrastructureValidationError,
        match="references unknown node 'missing-node'",
    ):
        InfrastructureValidator().validate(config)


def test_validator_rejects_duplicate_topology_node_reference() -> None:
    config = build_valid_topology_config()
    assert config.topology is not None
    config.topology.devices.append(
        TopologyDeviceConfig(
            id="duplicate-node",
            label="Duplicate node",
            kind=TopologyDeviceKind.SERVER,
            node="infra-01",
        )
    )

    with pytest.raises(
        InfrastructureValidationError,
        match="Topology node references must be unique",
    ):
        InfrastructureValidator().validate(config)


def test_validator_rejects_unknown_link_device() -> None:
    config = build_valid_topology_config()
    assert config.topology is not None
    config.topology.links.append(
        TopologyLinkConfig(
            id="missing-link",
            source="router",
            target="missing",
            kind=TopologyLinkKind.ETHERNET,
        )
    )

    with pytest.raises(
        InfrastructureValidationError,
        match="references unknown devices: missing",
    ):
        InfrastructureValidator().validate(config)


def test_validator_rejects_self_referencing_link() -> None:
    config = build_valid_topology_config()
    assert config.topology is not None
    config.topology.links.append(
        TopologyLinkConfig(
            id="self-link",
            source="router",
            target="router",
            kind=TopologyLinkKind.ETHERNET,
        )
    )

    with pytest.raises(
        InfrastructureValidationError,
        match="must connect two different devices",
    ):
        InfrastructureValidator().validate(config)


def test_validator_rejects_unknown_layout_device() -> None:
    config = build_valid_topology_config()
    assert config.topology is not None
    config.topology.layouts.append(
        TopologyLayoutConfig(
            id="invalid",
            label="Invalid",
            kind=TopologyLayoutKind.PHYSICAL,
            positions={
                "missing": TopologyGridPositionConfig(
                    column=0,
                    row=0,
                ),
            },
        )
    )

    with pytest.raises(
        InfrastructureValidationError,
        match="references unknown devices: missing",
    ):
        InfrastructureValidator().validate(config)


def test_validator_rejects_duplicate_grid_position() -> None:
    config = build_valid_topology_config()
    assert config.topology is not None

    layout = config.topology.layouts[0]
    layout.positions["infra"] = TopologyGridPositionConfig(
        column=0,
        row=0,
    )

    with pytest.raises(
        InfrastructureValidationError,
        match="contains duplicate grid positions",
    ):
        InfrastructureValidator().validate(config)


def test_validator_rejects_invalid_topology_device_address() -> None:
    config = build_valid_topology_config()
    assert config.topology is not None
    invalid_device = config.topology.devices[0].model_copy(
        update={"address": "not_an_ip"}
    )
    invalid_topology = config.topology.model_copy(
        update={
            "devices": [
                invalid_device,
                *config.topology.devices[1:],
            ]
        }
    )
    config = config.model_copy(update={"topology": invalid_topology})

    with pytest.raises(
        InfrastructureValidationError,
        match="Invalid host or IP address for topology device 'router'",
    ):
        InfrastructureValidator().validate(config)


def test_validator_accepts_hostname_endpoint_and_topology_address() -> None:
    config = build_valid_topology_config()
    assert config.topology is not None
    node = config.nodes[0].model_copy(
        update={
            "endpoint": NodeEndpointConfig(
                type="hostname", address="infra-01.ohana.lan"
            )
        }
    )
    device = config.topology.devices[0].model_copy(
        update={"address": "infra-01.ohana.lan"}
    )
    topology = config.topology.model_copy(
        update={"devices": [device, *config.topology.devices[1:]]}
    )
    config = config.model_copy(
        update={"nodes": [node, *config.nodes[1:]], "topology": topology}
    )

    InfrastructureValidator().validate(config)


def test_validator_rejects_hostname_with_underscore() -> None:
    config = build_valid_topology_config()
    assert config.topology is not None
    device = config.topology.devices[0].model_copy(
        update={"address": "she_01.ohana.lan"}
    )
    topology = config.topology.model_copy(
        update={"devices": [device, *config.topology.devices[1:]]}
    )
    config = config.model_copy(update={"topology": topology})

    with pytest.raises(InfrastructureValidationError):
        InfrastructureValidator().validate(config)
