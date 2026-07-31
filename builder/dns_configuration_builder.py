"""Build DNS runtime configuration from declarative configuration."""

from configuration.dns import DNSPluginConfig
from infrastructure import Infrastructure, Service, ServiceType
from plugins.dns.dns_config import (
    DNSConfig,
    DNSPolicyConfig,
    DNSServerConfig,
)


class DNSConfigurationBuilder:
    """Build DNS plugin configuration from infrastructure services."""

    def build(
        self,
        infrastructure: Infrastructure,
        config: DNSPluginConfig,
    ) -> DNSConfig:
        """Build a DNSConfig from every DNS service in the infrastructure."""
        servers = [
            self._build_server(service)
            for service in infrastructure.find_services(ServiceType.DNS)
        ]

        return DNSConfig(
            servers=servers,
            queries=config.queries.copy(),
            timeout=config.timeout,
            retries=config.retries,
            policy=DNSPolicyConfig(
                minimum_healthy_servers=(config.policy.minimum_healthy_servers),
            ),
        )

    @staticmethod
    def _build_server(service: Service) -> DNSServerConfig:
        """Convert one infrastructure DNS service into plugin configuration."""
        if service.endpoint is None:
            raise LookupError(f"DNS service {service.name!r} has no endpoint.")

        return DNSServerConfig(
            name=service.name,
            address=service.endpoint.address,
            enabled=(service.enabled and service.endpoint.enabled),
            node_id=(
                service.metadata.get("node_id")
                if isinstance(service.metadata.get("node_id"), str)
                else None
            ),
        )
