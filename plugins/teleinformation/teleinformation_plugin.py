"""Linky Téléinformation capability plugin."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from plugin.plugin import Plugin
from plugin.plugin_context import PluginContext
from plugin.plugin_manifest import PluginManifest
from plugin.plugin_runtime import PluginState
from plugins.teleinformation.teleinformation_check import TeleinformationCheck
from plugins.teleinformation.teleinformation_config import TeleinformationConfig
from plugins.teleinformation.teleinformation_result import TeleinformationValue

if TYPE_CHECKING:
    from observer.observer_result import ObserverResult

_INDEX_ARGUMENTS = {
    "blue_off_peak": "blue_off_peak_entity_id",
    "blue_peak": "blue_peak_entity_id",
    "white_off_peak": "white_off_peak_entity_id",
    "white_peak": "white_peak_entity_id",
    "red_off_peak": "red_off_peak_entity_id",
    "red_peak": "red_peak_entity_id",
}


class TeleinformationPlugin(Plugin):
    """Plugin responsible for Linky Téléinformation freshness."""

    def __init__(
        self,
        *,
        check: TeleinformationCheck | None = None,
        config: TeleinformationConfig | None = None,
    ) -> None:
        self._state = PluginState.LOADED
        self._check = check or TeleinformationCheck()
        self.config = config or TeleinformationConfig()

    @property
    def name(self) -> str:
        return "teleinformation"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        """Return the Téléinformation plugin manifest."""
        return PluginManifest(
            name="teleinformation",
            version="0.1.1",
            description=(
                "Linky teleinformation freshness and Tempo tariff plugin "
                "through Home Assistant."
            ),
        )

    def register(self, context: PluginContext) -> None:
        """Register the plugin in the Ohana-Agent context."""
        del context
        self._state = PluginState.REGISTERED

    def execute(self, **kwargs: Any) -> ObserverResult:
        """Check one configured Linky Téléinformation service."""
        from observer.observer_result import ObserverResult

        service_id = self._required_text(kwargs.get("service_id"), "service_id")
        service_name = self._optional_text(kwargs.get("service_name")) or service_id
        node_id = self._required_text(kwargs.get("node_id"), "node_id")
        apparent_power_entity_id = self._required_text(
            kwargs.get("apparent_power_entity_id"),
            "apparent_power_entity_id",
        )
        tariff_entity_id = self._required_text(
            kwargs.get("tariff_entity_id"),
            "tariff_entity_id",
        )
        maximum_age_seconds = kwargs.get(
            "maximum_age_seconds",
            self.config.maximum_age_seconds,
        )

        if (
            isinstance(maximum_age_seconds, bool)
            or not isinstance(maximum_age_seconds, int)
            or maximum_age_seconds <= 0
        ):
            raise ValueError(
                "TeleinformationPlugin.execute() requires a positive "
                "'maximum_age_seconds' argument."
            )

        index_entity_ids = {
            index_key: entity_id
            for index_key, argument_name in _INDEX_ARGUMENTS.items()
            if (
                entity_id := self._optional_entity_id(
                    kwargs.get(argument_name),
                    argument_name,
                )
            )
            is not None
        }
        started_at = perf_counter()
        result = self._check.check(
            service_name,
            apparent_power_entity_id,
            tariff_entity_id,
            index_entity_ids=index_entity_ids,
            home_assistant_url=self.config.home_assistant_url,
            access_token=self.config.access_token,
            access_token_environment_variable=(
                self.config.access_token_environment_variable
            ),
            maximum_age_seconds=maximum_age_seconds,
            timeout=self.config.timeout,
            retries=self.config.retries,
            verify_tls=self.config.verify_tls,
        )
        elapsed_ms = (perf_counter() - started_at) * 1000
        message = self._message(result)

        return ObserverResult(
            success=result.healthy,
            latency=elapsed_ms,
            message=message,
            check="teleinformation.freshness",
            description=(
                "Vérifie que Home Assistant reçoit toujours la téléinformation "
                "Linky et détermine la période Tempo courante."
            ),
            metadata={
                "target_type": "service",
                "service_id": service_id,
                "service_name": service_name,
                "node_id": node_id,
                "apparent_power": self._value_metadata(result.apparent_power),
                "tariff_entity": self._value_metadata(result.tariff_value),
                "tariff_number": (
                    result.tariff.number if result.tariff is not None else None
                ),
                "tariff_color": (
                    result.tariff.color if result.tariff is not None else None
                ),
                "tariff_period": (
                    result.tariff.period if result.tariff is not None else None
                ),
                "tariff_label": (
                    result.tariff.label if result.tariff is not None else None
                ),
                "active_index": (
                    self._value_metadata(result.active_index)
                    if result.active_index is not None
                    else None
                ),
                "indexes": {
                    key: self._value_metadata(value)
                    for key, value in result.indexes.items()
                },
                "maximum_age_seconds": maximum_age_seconds,
                "attempts": result.attempts,
                "home_assistant_url": self.config.home_assistant_url,
                "verify_tls": self.config.verify_tls,
                "error": result.error,
            },
        )

    def reconfigure(self, config: TeleinformationConfig) -> None:
        """Replace Téléinformation services and policy."""
        self.config = config

    @staticmethod
    def _message(result: Any) -> str:
        if not result.healthy:
            return result.error or (
                f"Téléinformation indisponible pour {result.meter_name}."
            )

        power = result.apparent_power
        power_text = (
            f"{power.value:g} {power.unit or 'VA'}"
            if power.value is not None
            else "puissance inconnue"
        )
        tariff_text = (
            result.tariff.label if result.tariff is not None else "tarif inconnu"
        )
        active_index = result.active_index
        index_text = ""

        if active_index is not None and active_index.value is not None:
            index_text = (
                f", index {active_index.value:g} {active_index.unit or ''}".rstrip()
            )

        return (
            f"Téléinformation fraîche pour {result.meter_name} : "
            f"{power_text}, {tariff_text}{index_text}."
        )

    @staticmethod
    def _required_text(value: object, field_name: str) -> str:
        normalized = TeleinformationPlugin._optional_text(value)

        if normalized is None:
            raise ValueError(
                "TeleinformationPlugin.execute() requires a non-empty "
                f"'{field_name}' argument."
            )

        return normalized

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None

        normalized = value.strip()
        return normalized or None

    @classmethod
    def _optional_entity_id(
        cls,
        value: object,
        field_name: str,
    ) -> str | None:
        normalized = cls._optional_text(value)

        if normalized is not None and "." not in normalized:
            raise ValueError(
                f"TeleinformationPlugin.execute() received an invalid {field_name}."
            )

        return normalized

    @staticmethod
    def _value_metadata(value: TeleinformationValue) -> dict[str, object | None]:
        return {
            "entity_id": value.entity_id,
            "value": value.value,
            "unit": value.unit,
            "reported_at": (
                value.reported_at.isoformat() if value.reported_at is not None else None
            ),
            "age_seconds": value.age_seconds,
        }
