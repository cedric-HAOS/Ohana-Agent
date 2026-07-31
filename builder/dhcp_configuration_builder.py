"""Build DHCP runtime configuration from declarative configuration."""

from pathlib import Path

from configuration.dhcp import DHCPPluginConfig
from infrastructure import Infrastructure, Service, ServiceType
from plugins.dhcp.dhcp_config import (
    DHCPConfig,
    DHCPPolicyConfig,
    DHCPServerConfig,
)

DNSMASQ_STATUS_COMMAND = (
    "/usr/bin/systemctl",
    "is-active",
    "dnsmasq.service",
)


class DHCPConfigurationBuilder:
    """Build DHCP plugin configuration from infrastructure services."""

    def build(
        self,
        infrastructure: Infrastructure,
        config: DHCPPluginConfig,
        *,
        server_node_id: str,
        main_config_path: Path,
        leases_path: Path,
    ) -> DHCPConfig:
        """Build the local DHCP runtime from its infrastructure node."""
        node = infrastructure.get_node(server_node_id)

        if node is None:
            raise LookupError(f"DHCP server node not found: {server_node_id!r}.")

        servers = [
            self._build_server(service)
            for service in node.services
            if service.type is ServiceType.DHCP
        ]

        return DHCPConfig(
            servers=servers,
            main_config_path=main_config_path,
            leases_path=leases_path,
            service_status_command=(
                DNSMASQ_STATUS_COMMAND if config.check_service_active else None
            ),
            timeout=config.timeout,
            policy=DHCPPolicyConfig(
                maximum_pool_usage_percent=(config.policy.maximum_pool_usage_percent),
            ),
        )

    @staticmethod
    def _build_server(service: Service) -> DHCPServerConfig:
        """Convert one infrastructure DHCP service into plugin configuration."""
        if service.endpoint is None:
            raise LookupError(f"DHCP service {service.name!r} has no endpoint.")

        port = 67 if service.endpoint.port is None else service.endpoint.port

        if not 1 <= port <= 65_535:
            raise ValueError(
                f"DHCP service {service.name!r} has an invalid port: {port}."
            )

        return DHCPServerConfig(
            name=service.name,
            address=service.endpoint.address,
            port=port,
            enabled=(service.enabled and service.endpoint.enabled),
            node_id=(
                service.metadata.get("node_id")
                if isinstance(service.metadata.get("node_id"), str)
                else None
            ),
        )
