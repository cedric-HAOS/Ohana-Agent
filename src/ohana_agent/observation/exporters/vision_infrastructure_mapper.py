"""Mapping of Ohana-Agent infrastructure to Ohana-Vision payloads."""

from copy import deepcopy
from typing import Any

from ohana_agent.configuration.infrastructure import (
    InfrastructureConfig,
    TopologyConfig,
    TopologyDeviceConfig,
)


class VisionInfrastructureMapper:
    """Convert Agent infrastructure configuration to the Vision contract."""

    SCHEMA_VERSION = 1

    def to_payload(
        self,
        config: InfrastructureConfig,
    ) -> dict[str, Any]:
        """Build the infrastructure payload expected by Ohana-Vision."""
        payload: dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "infrastructure_id": config.infrastructure.id,
            "name": config.infrastructure.name,
            "environment": config.infrastructure.environment,
            "metadata": {
                "version": config.metadata.version,
                "tags": list(config.metadata.tags),
            },
            "nodes": [
                {
                    "node_id": node.id,
                    "name": node.name,
                    "description": node.description,
                    "endpoint": {
                        "type": node.endpoint.type,
                        "address": node.endpoint.address,
                    },
                }
                for node in config.nodes
            ],
            "services": [
                {
                    "service_id": service.id,
                    "name": service.name,
                    "type": service.type,
                    "node_id": service.node,
                    "port": service.port,
                    "implementation": service.implementation,
                    "enabled": service.enabled,
                    "critical": service.critical,
                    "metadata": deepcopy(service.metadata),
                }
                for service in config.services
            ],
        }

        if config.topology is not None:
            payload["topology"] = self._map_topology(
                config.topology,
                config=config,
            )

        return payload

    def _map_topology(
        self,
        topology: TopologyConfig,
        *,
        config: InfrastructureConfig,
    ) -> dict[str, Any]:
        """Map the complete topology section."""
        nodes_by_id = {node.id: node for node in config.nodes}

        return {
            "devices": [
                self._map_device(
                    device,
                    nodes_by_id=nodes_by_id,
                )
                for device in topology.devices
            ],
            "links": [
                {
                    "link_id": link.id,
                    "source_device_id": link.source,
                    "target_device_id": link.target,
                    "kind": link.kind.value,
                    "direction": link.direction.value,
                    "label": link.label,
                    "bandwidth_mbps": link.bandwidth_mbps,
                    "metadata": deepcopy(link.metadata),
                }
                for link in topology.links
            ],
            "layouts": [
                {
                    "layout_id": layout.id,
                    "label": layout.label,
                    "kind": layout.kind.value,
                    "positions": {
                        device_id: {
                            "column": position.column,
                            "row": position.row,
                        }
                        for device_id, position in layout.positions.items()
                    },
                    "metadata": deepcopy(layout.metadata),
                }
                for layout in topology.layouts
            ],
            "metadata": deepcopy(topology.metadata),
        }

    @staticmethod
    def _map_device(
        device: TopologyDeviceConfig,
        *,
        nodes_by_id: dict[str, Any],
    ) -> dict[str, Any]:
        """Map one topology device and resolve its node address."""
        address = device.address

        if address is None and device.node is not None:
            node = nodes_by_id.get(device.node)

            if node is not None:
                address = node.endpoint.address

        return {
            "device_id": device.id,
            "label": device.label,
            "kind": device.kind.value,
            "node_id": device.node,
            "address": address,
            "metadata": deepcopy(device.metadata),
        }
