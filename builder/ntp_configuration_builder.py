"""Build NTP runtime configuration from declarative configuration."""

from configuration.ntp import NTPPluginConfig
from infrastructure import Infrastructure, Service, ServiceType
from plugins.ntp.ntp_config import (
    NTPConfig,
    NTPPolicyConfig,
    NTPServerConfig,
)


class NTPConfigurationBuilder:
    """Build NTP plugin configuration from infrastructure services."""

    def build(
        self,
        infrastructure: Infrastructure,
        config: NTPPluginConfig,
    ) -> NTPConfig:
        """Build an NTPConfig from every NTP service in the infrastructure."""
        servers = [
            self._build_server(service)
            for service in infrastructure.find_services(ServiceType.NTP)
        ]

        return NTPConfig(
            servers=servers,
            timeout=config.timeout,
            retries=config.retries,
            policy=NTPPolicyConfig(
                maximum_offset_ms=config.policy.maximum_offset_ms,
                maximum_stratum=config.policy.maximum_stratum,
            ),
        )

    @staticmethod
    def _build_server(service: Service) -> NTPServerConfig:
        """Convert one infrastructure NTP service into plugin configuration."""
        if service.endpoint is None:
            raise LookupError(f"NTP service {service.name!r} has no endpoint.")

        port = 123 if service.endpoint.port is None else service.endpoint.port

        if not 1 <= port <= 65_535:
            raise ValueError(
                f"NTP service {service.name!r} has an invalid port: {port}."
            )

        return NTPServerConfig(
            name=service.name,
            address=service.endpoint.address,
            port=port,
            enabled=(service.enabled and service.endpoint.enabled),
        )
