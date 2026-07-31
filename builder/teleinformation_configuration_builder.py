"""Build Téléinformation runtime configuration from infrastructure services."""

from __future__ import annotations

import re

from configuration.teleinformation import TeleinformationPluginConfig
from infrastructure import Infrastructure, Service, ServiceType
from plugins.teleinformation.teleinformation_config import (
    TeleinformationConfig,
    TeleinformationServiceConfig,
)

_ENTITY_FIELDS = (
    "blue_off_peak_entity_id",
    "blue_peak_entity_id",
    "white_off_peak_entity_id",
    "white_peak_entity_id",
    "red_off_peak_entity_id",
    "red_peak_entity_id",
)
_METER_ENTITY_PATTERN = re.compile(r"(?:^|\.)teleinfo_([0-9]+)_", re.IGNORECASE)


class TeleinformationConfigurationBuilder:
    """Build targets from explicitly declared Téléinformation services."""

    def build(
        self,
        infrastructure: Infrastructure,
        config: TeleinformationPluginConfig,
    ) -> TeleinformationConfig:
        """Build runtime targets from services of type teleinformation."""
        services = [
            self._build_service(
                service,
                mode=config.mode,
                default_maximum_age=config.maximum_age_seconds,
            )
            for service in infrastructure.find_services(ServiceType.TELEINFORMATION)
        ]

        return TeleinformationConfig(
            services=services,
            mode=config.mode,
            listen_host=config.listen_host,
            listen_port=config.listen_port,
            ingestion_token=config.ingestion_token,
            ingestion_token_environment_variable=(
                config.ingestion_token_environment_variable
            ),
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
        mode: str,
        default_maximum_age: int,
    ) -> TeleinformationServiceConfig:
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

        if isinstance(maximum_age, bool) or not isinstance(maximum_age, int):
            raise ValueError(
                f"Téléinformation service {service.name!r} has an invalid "
                "maximum_age_seconds."
            )
        if maximum_age <= 0:
            raise ValueError(
                f"Téléinformation service {service.name!r} must define a positive "
                "maximum_age_seconds."
            )

        apparent_power_entity_id = cls._optional_text(
            service.metadata.get("apparent_power_entity_id")
        )
        tariff_entity_id = cls._optional_text(service.metadata.get("tariff_entity_id"))
        entity_values = {
            field: cls._optional_text(service.metadata.get(field))
            for field in _ENTITY_FIELDS
        }

        if mode == "home_assistant":
            apparent_power_entity_id = cls._required_text(
                apparent_power_entity_id,
                field="apparent_power_entity_id",
                service_id=service.name,
            )
            tariff_entity_id = cls._required_text(
                tariff_entity_id,
                field="tariff_entity_id",
                service_id=service.name,
            )
            cls._validate_entity_id(apparent_power_entity_id, service_id=service.name)
            cls._validate_entity_id(tariff_entity_id, service_id=service.name)
            for entity_id in entity_values.values():
                if entity_id is not None:
                    cls._validate_entity_id(entity_id, service_id=service.name)

        meter_id = cls._optional_text(service.metadata.get("meter_id"))
        if meter_id is None:
            meter_id = cls._infer_meter_id(apparent_power_entity_id, tariff_entity_id)
        if mode == "direct_http" and meter_id is None:
            raise ValueError(
                f"Téléinformation service {service.name!r} is missing meter_id."
            )

        source_id = cls._optional_text(service.metadata.get("source_id")) or "rpi-linky"

        return TeleinformationServiceConfig(
            name=service.name,
            label=label,
            node_id=node_id,
            meter_id=meter_id,
            source_id=source_id,
            apparent_power_entity_id=apparent_power_entity_id,
            tariff_entity_id=tariff_entity_id,
            maximum_age_seconds=maximum_age,
            enabled=(
                service.enabled
                and (service.endpoint is None or service.endpoint.enabled)
            ),
            **entity_values,
        )

    @staticmethod
    def _infer_meter_id(*entity_ids: str | None) -> str | None:
        for entity_id in entity_ids:
            if entity_id is None:
                continue
            match = _METER_ENTITY_PATTERN.search(entity_id)
            if match is not None:
                return match.group(1)
        return None

    @staticmethod
    def _required_text(value: object, *, field: str, service_id: str) -> str:
        normalized = TeleinformationConfigurationBuilder._optional_text(value)
        if normalized is None:
            raise ValueError(
                f"Téléinformation service {service_id!r} is missing {field}."
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
                f"Téléinformation service {service_id!r}."
            )
