"""Generic Home Assistant telemetry freshness capability plugin."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from plugin.plugin import Plugin
from plugin.plugin_context import PluginContext
from plugin.plugin_manifest import PluginManifest
from plugin.plugin_runtime import PluginState
from plugins.home_assistant_telemetry.home_assistant_telemetry_check import (
    HomeAssistantTelemetryCheck,
)
from plugins.home_assistant_telemetry.home_assistant_telemetry_config import (
    HomeAssistantTelemetryConfig,
)
from plugins.home_assistant_telemetry.home_assistant_telemetry_result import (
    HomeAssistantTelemetryValue,
)

if TYPE_CHECKING:
    from observer.observer_result import ObserverResult


class HomeAssistantTelemetryPlugin(Plugin):
    """Plugin responsible for generic Home Assistant entity freshness."""

    def __init__(
        self,
        *,
        check: HomeAssistantTelemetryCheck | None = None,
        config: HomeAssistantTelemetryConfig | None = None,
    ) -> None:
        self._state = PluginState.LOADED
        self._check = check or HomeAssistantTelemetryCheck()
        self.config = config or HomeAssistantTelemetryConfig()

    @property
    def name(self) -> str:
        return "home_assistant_telemetry"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="home_assistant_telemetry",
            version="1.0.0",
            description=(
                "Generic Home Assistant entity freshness plugin for Ohana-Agent."
            ),
        )

    def register(self, context: PluginContext) -> None:
        del context
        self._state = PluginState.REGISTERED

    def execute(self, **kwargs: Any) -> ObserverResult:
        from observer.observer_result import ObserverResult

        service_id = kwargs.get("service_id")
        service_name = kwargs.get("service_name")
        node_id = kwargs.get("node_id")
        primary_entity_id = kwargs.get(
            "primary_entity_id",
            kwargs.get("power_entity_id"),
        )
        secondary_entity_id = kwargs.get(
            "secondary_entity_id",
            kwargs.get("energy_entity_id"),
        )
        maximum_age_seconds = kwargs.get(
            "maximum_age_seconds",
            self.config.maximum_age_seconds,
        )

        if not isinstance(service_id, str) or not service_id.strip():
            raise ValueError(
                "HomeAssistantTelemetryPlugin.execute() requires a non-empty "
                "'service_id' argument."
            )

        if not isinstance(service_name, str) or not service_name.strip():
            service_name = service_id

        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError(
                "HomeAssistantTelemetryPlugin.execute() requires a non-empty "
                "'node_id' argument."
            )

        if not isinstance(primary_entity_id, str) or not primary_entity_id.strip():
            raise ValueError(
                "HomeAssistantTelemetryPlugin.execute() requires a non-empty "
                "'primary_entity_id' argument."
            )

        if secondary_entity_id is not None and (
            not isinstance(secondary_entity_id, str) or not secondary_entity_id.strip()
        ):
            raise ValueError(
                "HomeAssistantTelemetryPlugin.execute() requires "
                "'secondary_entity_id' to be null or non-empty."
            )

        if (
            isinstance(maximum_age_seconds, bool)
            or not isinstance(maximum_age_seconds, int)
            or maximum_age_seconds <= 0
        ):
            raise ValueError(
                "HomeAssistantTelemetryPlugin.execute() requires a positive "
                "'maximum_age_seconds' argument."
            )

        started_at = perf_counter()
        check_arguments = {
            "home_assistant_url": self.config.home_assistant_url,
            "access_token": self.config.access_token,
            "access_token_environment_variable": (
                self.config.access_token_environment_variable
            ),
            "maximum_age_seconds": maximum_age_seconds,
            "timeout": self.config.timeout,
            "retries": self.config.retries,
            "verify_tls": self.config.verify_tls,
        }
        resolved_secondary_entity_id = (
            secondary_entity_id.strip()
            if isinstance(secondary_entity_id, str)
            else None
        )

        try:
            result = self._check.check(
                service_name.strip(),
                primary_entity_id.strip(),
                secondary_entity_id=resolved_secondary_entity_id,
                **check_arguments,
            )
        except TypeError as error:
            if "secondary_entity_id" not in str(error):
                raise

            # Compatibility with an injected ShellyTelemetryCheck implementation.
            result = self._check.check(
                service_name.strip(),
                primary_entity_id.strip(),
                energy_entity_id=resolved_secondary_entity_id,
                **check_arguments,
            )
        elapsed_ms = (perf_counter() - started_at) * 1000
        resolved_service_name = getattr(
            result,
            "service_name",
            getattr(result, "device_name", service_name.strip()),
        )
        primary = getattr(result, "primary", getattr(result, "power", None))
        secondary = getattr(
            result,
            "secondary",
            getattr(result, "energy", None),
        )

        if primary is None:
            raise RuntimeError("Telemetry check returned no primary value.")

        message = (
            f"Home Assistant telemetry for {resolved_service_name} is fresh; "
            f"primary value is {primary.value:g} "
            f"{primary.unit or ''}.".rstrip()
            if result.healthy and primary.value is not None
            else result.error
            or f"Home Assistant telemetry for {resolved_service_name} is unavailable."
        )

        metadata = {
            "target_type": "service",
            "service_id": service_id.strip(),
            "service_name": service_name.strip(),
            "node_id": node_id.strip(),
            "primary": self._value_metadata(primary),
            "secondary": self._value_metadata(secondary),
            "attempts": result.attempts,
            "maximum_age_seconds": maximum_age_seconds,
            "error": result.error,
        }
        if "power_entity_id" in kwargs:
            metadata["power"] = metadata["primary"]
            metadata["energy"] = metadata["secondary"]

        return ObserverResult(
            success=result.healthy,
            latency=elapsed_ms,
            message=message,
            check="home_assistant.telemetry.freshness",
            description=(
                "Check that Home Assistant still receives a configured entity."
            ),
            metadata=metadata,
        )

    def test(self, **kwargs: Any) -> ObserverResult:
        return self.execute(**kwargs)

    def reconfigure(self, config: HomeAssistantTelemetryConfig) -> None:
        self.config = config

    @staticmethod
    def _value_metadata(
        value: HomeAssistantTelemetryValue | None,
    ) -> dict[str, object] | None:
        if value is None:
            return None

        return {
            "entity_id": value.entity_id,
            "value": value.value,
            "unit": value.unit,
            "reported_at": (
                value.reported_at.isoformat() if value.reported_at is not None else None
            ),
            "age_seconds": value.age_seconds,
        }
