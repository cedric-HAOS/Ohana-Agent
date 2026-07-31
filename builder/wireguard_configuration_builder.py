"""Build Freebox WireGuard runtime configuration from infrastructure services."""

from configuration.wireguard import WireGuardPluginConfig
from infrastructure import Infrastructure, Service, ServiceType
from plugins.wireguard.wireguard_config import (
    WireGuardConfig,
    WireGuardServiceConfig,
)


class WireGuardConfigurationBuilder:
    """Build WireGuard plugin configuration from declared Freebox services."""

    def build(
        self,
        infrastructure: Infrastructure,
        config: WireGuardPluginConfig,
    ) -> WireGuardConfig:
        """Build a WireGuardConfig from every WireGuard service."""
        services = [
            self._build_service(service)
            for service in infrastructure.find_services(ServiceType.WIREGUARD)
        ]

        return WireGuardConfig(
            services=services,
            timeout=config.timeout,
            retries=config.retries,
            app_id=config.app_id,
            app_version=config.app_version,
            app_token=config.app_token,
            verify_tls=config.verify_tls,
        )

    @staticmethod
    def _build_service(service: Service) -> WireGuardServiceConfig:
        """Convert one Freebox WireGuard service into runtime configuration."""
        if service.endpoint is None:
            raise LookupError(
                f"WireGuard service {service.name!r} has no Freebox endpoint."
            )

        scheme = service.metadata.get("scheme", "http")
        server_name = service.metadata.get("server_name", "wireguard")

        if not isinstance(scheme, str) or scheme not in {"http", "https"}:
            raise ValueError(
                f"WireGuard service {service.name!r} has an invalid scheme."
            )

        if not isinstance(server_name, str) or not server_name.strip():
            raise ValueError(
                f"WireGuard service {service.name!r} has an invalid server_name."
            )

        port = service.endpoint.port
        authority = service.endpoint.address

        if port is not None:
            if not 1 <= port <= 65_535:
                raise ValueError(
                    f"WireGuard service {service.name!r} has an invalid port: {port}."
                )
            authority = f"{authority}:{port}"

        return WireGuardServiceConfig(
            name=service.name,
            base_url=f"{scheme}://{authority}",
            server_name=server_name.strip(),
            enabled=(service.enabled and service.endpoint.enabled),
            node_id=(
                service.metadata.get("node_id")
                if isinstance(service.metadata.get("node_id"), str)
                else None
            ),
        )
