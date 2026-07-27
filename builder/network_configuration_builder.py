"""Build network presence runtime configuration from the topology."""

from configuration.infrastructure import InfrastructureConfig
from configuration.network import NetworkPluginConfig
from plugins.network.network_config import NetworkConfig, NetworkDeviceConfig


class NetworkConfigurationBuilder:
    """Discover addressable topology devices from infrastructure.yaml."""

    def build(
        self,
        infrastructure: InfrastructureConfig,
        config: NetworkPluginConfig,
    ) -> NetworkConfig:
        """Build one presence target per topology device with an address."""
        topology = infrastructure.topology

        if topology is None:
            return NetworkConfig(
                timeout=config.timeout,
                retries=config.retries,
                failure_threshold=config.failure_threshold,
            )

        nodes_by_id = {node.id: node for node in infrastructure.nodes}
        devices: list[NetworkDeviceConfig] = []

        for device in topology.devices:
            address = device.address

            if address is None and device.node is not None:
                node = nodes_by_id.get(device.node)
                address = node.endpoint.address if node is not None else None

            if address is None or not address.strip():
                continue

            network_presence_enabled = device.metadata.get(
                "network_presence_enabled",
                True,
            )

            devices.append(
                NetworkDeviceConfig(
                    name=device.id,
                    label=device.label,
                    address=address.strip(),
                    node_id=device.node,
                    enabled=(
                        network_presence_enabled
                        if isinstance(network_presence_enabled, bool)
                        else True
                    ),
                )
            )

        return NetworkConfig(
            devices=devices,
            timeout=config.timeout,
            retries=config.retries,
            failure_threshold=config.failure_threshold,
        )
