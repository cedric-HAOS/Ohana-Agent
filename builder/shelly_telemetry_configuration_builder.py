"""Build Shelly telemetry runtime configuration from infrastructure services."""

from configuration.shelly_telemetry import ShellyTelemetryPluginConfig
from infrastructure import Infrastructure, Service, ServiceType
from plugins.shelly_telemetry.shelly_telemetry_config import (
    ShellyTelemetryConfig,
    ShellyTelemetryServiceConfig,
)


class ShellyTelemetryConfigurationBuilder:
    """Build targets from explicitly declared Shelly telemetry services."""

    def build(
        self,
        infrastructure: Infrastructure,
        config: ShellyTelemetryPluginConfig,
    ) -> ShellyTelemetryConfig:
        """Build runtime targets from services of type shelly_telemetry."""
        services = [
            self._build_service(service, default_maximum_age=config.maximum_age_seconds)
            for service in infrastructure.find_services(ServiceType.SHELLY_TELEMETRY)
        ]

        return ShellyTelemetryConfig(
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
    ) -> ShellyTelemetryServiceConfig:
        power_entity_id = cls._required_text(
            service.metadata.get("power_entity_id"),
            field="power_entity_id",
            service_id=service.name,
        )
        energy_entity_id = cls._optional_text(service.metadata.get("energy_entity_id"))
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

        cls._validate_entity_id(power_entity_id, service_id=service.name)

        if energy_entity_id is not None:
            cls._validate_entity_id(energy_entity_id, service_id=service.name)

        if isinstance(maximum_age, bool) or not isinstance(maximum_age, int):
            raise ValueError(
                f"Shelly telemetry service {service.name!r} has an invalid "
                "maximum_age_seconds."
            )

        if maximum_age <= 0:
            raise ValueError(
                f"Shelly telemetry service {service.name!r} must define a positive "
                "maximum_age_seconds."
            )

        return ShellyTelemetryServiceConfig(
            name=service.name,
            label=label,
            node_id=node_id,
            power_entity_id=power_entity_id,
            energy_entity_id=energy_entity_id,
            maximum_age_seconds=maximum_age,
            enabled=(
                service.enabled
                and (service.endpoint is None or service.endpoint.enabled)
            ),
        )

    @staticmethod
    def _required_text(value: object, *, field: str, service_id: str) -> str:
        normalized = ShellyTelemetryConfigurationBuilder._optional_text(value)

        if normalized is None:
            raise ValueError(
                f"Shelly telemetry service {service_id!r} is missing {field}."
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
                f"Shelly telemetry service {service_id!r}."
            )
