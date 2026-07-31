"""Build Home Assistant telemetry runtime configuration from services."""

from configuration.home_assistant_telemetry import (
    HomeAssistantTelemetryPluginConfig,
)
from infrastructure import Infrastructure, Service, ServiceType
from plugins.home_assistant_telemetry.home_assistant_telemetry_config import (
    HomeAssistantTelemetryConfig,
    HomeAssistantTelemetryServiceConfig,
)


class HomeAssistantTelemetryConfigurationBuilder:
    """Build targets from generic and legacy telemetry services."""

    def build(
        self,
        infrastructure: Infrastructure,
        config: HomeAssistantTelemetryPluginConfig,
    ) -> HomeAssistantTelemetryConfig:
        services = [
            self._build_service(
                service,
                default_maximum_age=config.maximum_age_seconds,
            )
            for node in infrastructure.nodes
            for service in node.services
            if service.type
            in {
                ServiceType.HOME_ASSISTANT_TELEMETRY,
                ServiceType.SHELLY_TELEMETRY,
            }
        ]

        return HomeAssistantTelemetryConfig(
            services=services,
            home_assistant_url=config.home_assistant_url,
            access_token=config.access_token,
            access_token_environment_variable=(
                config.access_token_environment_variable
            ),
            timeout=config.timeout,
            retries=config.retries,
            maximum_age_seconds=config.maximum_age_seconds,
            verify_tls=config.verify_tls,
        )

    @classmethod
    def _build_service(
        cls,
        service: Service,
        *,
        default_maximum_age: int,
    ) -> HomeAssistantTelemetryServiceConfig:
        primary_entity_id = cls._required_text(
            service.metadata.get(
                "primary_entity_id",
                service.metadata.get("power_entity_id"),
            ),
            field="primary_entity_id",
            service_id=service.name,
        )
        secondary_entity_id = cls._optional_text(
            service.metadata.get(
                "secondary_entity_id",
                service.metadata.get("energy_entity_id"),
            )
        )
        node_id = cls._required_text(
            service.metadata.get("node_id"),
            field="node_id",
            service_id=service.name,
        )
        label = cls._optional_text(service.metadata.get("label")) or service.name
        maximum_age = service.metadata.get(
            "maximum_age_seconds",
            default_maximum_age,
        )

        cls._validate_entity_id(primary_entity_id, service_id=service.name)

        if secondary_entity_id is not None:
            cls._validate_entity_id(secondary_entity_id, service_id=service.name)

        if isinstance(maximum_age, bool) or not isinstance(maximum_age, int):
            raise ValueError(
                f"Home Assistant telemetry service {service.name!r} has an invalid "
                "maximum_age_seconds."
            )

        if maximum_age <= 0:
            raise ValueError(
                f"Home Assistant telemetry service {service.name!r} must define "
                "a positive maximum_age_seconds."
            )

        return HomeAssistantTelemetryServiceConfig(
            name=service.name,
            label=label,
            node_id=node_id,
            primary_entity_id=primary_entity_id,
            secondary_entity_id=secondary_entity_id,
            maximum_age_seconds=maximum_age,
            enabled=(
                service.enabled
                and (service.endpoint is None or service.endpoint.enabled)
            ),
        )

    @staticmethod
    def _required_text(value: object, *, field: str, service_id: str) -> str:
        normalized = HomeAssistantTelemetryConfigurationBuilder._optional_text(value)

        if normalized is None:
            raise ValueError(
                f"Home Assistant telemetry service {service_id!r} is missing {field}."
            )

        return normalized

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None

        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _validate_entity_id(entity_id: str, *, service_id: str) -> None:
        if "." not in entity_id:
            raise ValueError(
                f"Invalid Home Assistant entity id {entity_id!r} for "
                f"telemetry service {service_id!r}."
            )
