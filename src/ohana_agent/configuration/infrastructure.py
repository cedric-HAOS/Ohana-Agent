from pydantic import Field

from ohana_agent.configuration.base import Config
from ohana_agent.configuration.enums import (
    TopologyDeviceKind,
    TopologyLayoutKind,
    TopologyLinkDirection,
    TopologyLinkKind,
)


class InfrastructureIdentityConfig(Config):
    id: str
    name: str
    environment: str = "production"


class InfrastructureMetadataConfig(Config):
    version: str = "1.0"
    tags: list[str] = Field(default_factory=list)


class NodeEndpointConfig(Config):
    type: str
    address: str


class NodeConfig(Config):
    id: str
    name: str
    description: str = ""
    endpoint: NodeEndpointConfig


class ServiceConfig(Config):
    id: str
    name: str
    type: str
    node: str
    port: int | None = None
    implementation: str | None = None
    enabled: bool = True
    critical: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class TopologyDeviceConfig(Config):
    id: str
    label: str
    kind: TopologyDeviceKind
    node: str | None = None
    address: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class TopologyLinkConfig(Config):
    id: str
    source: str
    target: str
    kind: TopologyLinkKind
    direction: TopologyLinkDirection = TopologyLinkDirection.BIDIRECTIONAL
    label: str | None = None
    bandwidth_mbps: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
    )
    metadata: dict[str, object] = Field(default_factory=dict)


class TopologyGridPositionConfig(Config):
    """Logical position of one device in a Vision layout grid."""

    column: int = Field(ge=0)
    row: int = Field(ge=0)


class TopologyLayoutConfig(Config):
    id: str
    label: str
    kind: TopologyLayoutKind
    positions: dict[str, TopologyGridPositionConfig] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class TopologyConfig(Config):
    devices: list[TopologyDeviceConfig] = Field(default_factory=list)
    links: list[TopologyLinkConfig] = Field(default_factory=list)
    layouts: list[TopologyLayoutConfig] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class InfrastructureConfig(Config):
    infrastructure: InfrastructureIdentityConfig
    metadata: InfrastructureMetadataConfig = Field(
        default_factory=InfrastructureMetadataConfig
    )
    nodes: list[NodeConfig] = Field(default_factory=list)
    services: list[ServiceConfig] = Field(default_factory=list)
    topology: TopologyConfig | None = None
