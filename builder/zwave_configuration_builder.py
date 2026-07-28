"""Build Z-Wave runtime configuration from infrastructure services."""

from configuration.zwave import ZWavePluginConfig
from infrastructure import Infrastructure, Service, ServiceType
from plugins.zwave.zwave_config import ZWaveConfig, ZWaveServiceConfig


class ZWaveConfigurationBuilder:
    """Build Z-Wave plugin configuration from Z-Wave services."""

    def build(
        self,
        infrastructure: Infrastructure,
        config: ZWavePluginConfig,
    ) -> ZWaveConfig:
        """Build a ZWaveConfig from every Z-Wave service."""
        services = [
            self._build_service(service)
            for service in infrastructure.find_services(ServiceType.ZWAVE)
        ]

        return ZWaveConfig(
            services=services,
            timeout=config.timeout,
            retries=config.retries,
            verify_tls=config.verify_tls,
        )

    @staticmethod
    def _build_service(service: Service) -> ZWaveServiceConfig:
        """Convert one infrastructure Z-Wave service into plugin configuration."""
        if service.endpoint is None:
            raise LookupError(f"Z-Wave service {service.name!r} has no endpoint.")

        port = 8091 if service.endpoint.port is None else service.endpoint.port

        if not 1 <= port <= 65_535:
            raise ValueError(
                f"Z-Wave service {service.name!r} has an invalid port: {port}."
            )

        scheme = service.metadata.get("scheme", "http")
        health_path = service.metadata.get("health_path", "/health/zwave")

        if not isinstance(scheme, str) or scheme not in {"http", "https"}:
            raise ValueError(f"Z-Wave service {service.name!r} has an invalid scheme.")

        if not isinstance(health_path, str) or not health_path.startswith("/"):
            raise ValueError(
                f"Z-Wave service {service.name!r} has an invalid health path."
            )

        return ZWaveServiceConfig(
            name=service.name,
            url=(f"{scheme}://{service.endpoint.address}:{port}{health_path}"),
            enabled=(service.enabled and service.endpoint.enabled),
        )
