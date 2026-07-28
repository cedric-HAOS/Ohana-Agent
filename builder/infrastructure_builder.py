from configuration.infrastructure import InfrastructureConfig, NodeConfig
from infrastructure.endpoint import Endpoint
from infrastructure.enums import EndpointType, ServiceType
from infrastructure.infrastructure import Infrastructure
from infrastructure.node import Node
from infrastructure.service import Service


class InfrastructureBuilder:
    """Builds Infrastructure objects from InfrastructureConfig."""

    def build(
        self,
        config: InfrastructureConfig,
    ) -> Infrastructure:
        infrastructure = Infrastructure(
            name=config.infrastructure.name,
        )

        nodes = self._build_nodes(config)

        for node in nodes.values():
            infrastructure.add_node(node)

        self._build_services(config, nodes)

        return infrastructure

    def _build_nodes(
        self,
        config: InfrastructureConfig,
    ) -> dict[str, Node]:
        nodes: dict[str, Node] = {}

        for node_config in config.nodes:
            node = Node(
                name=node_config.id,
                description=node_config.description,
                endpoints=[
                    self._build_node_endpoint(node_config),
                ],
            )

            nodes[node_config.id] = node

        return nodes

    def _build_node_endpoint(
        self,
        node_config: NodeConfig,
    ) -> Endpoint:
        return Endpoint(
            type=EndpointType(node_config.endpoint.type),
            address=node_config.endpoint.address,
        )

    def _build_services(
        self,
        config: InfrastructureConfig,
        nodes: dict[str, Node],
    ) -> None:
        for service_config in config.services:
            node = nodes[service_config.node]
            node_endpoint = node.endpoints[0]

            service = Service(
                name=service_config.id,
                type=ServiceType(service_config.type),
                endpoint=Endpoint(
                    type=node_endpoint.type,
                    address=node_endpoint.address,
                    port=service_config.port,
                    enabled=service_config.enabled,
                ),
                enabled=service_config.enabled,
                metadata={
                    **service_config.metadata,
                    "implementation": service_config.implementation,
                    "critical": service_config.critical,
                },
            )

            node.add_service(service)
