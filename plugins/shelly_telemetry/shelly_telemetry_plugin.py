"""Shelly telemetry freshness capability plugin."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from plugin.plugin import Plugin
from plugin.plugin_context import PluginContext
from plugin.plugin_manifest import PluginManifest
from plugin.plugin_runtime import PluginState
from plugins.shelly_telemetry.shelly_telemetry_check import ShellyTelemetryCheck
from plugins.shelly_telemetry.shelly_telemetry_config import ShellyTelemetryConfig
from plugins.shelly_telemetry.shelly_telemetry_result import ShellyTelemetryValue

if TYPE_CHECKING:
    from observer.observer_result import ObserverResult


class ShellyTelemetryPlugin(Plugin):
    """Plugin responsible for Home Assistant Shelly telemetry freshness."""

    def __init__(
        self,
        *,
        check: ShellyTelemetryCheck | None = None,
        config: ShellyTelemetryConfig | None = None,
    ) -> None:
        self._state = PluginState.LOADED
        self._check = check or ShellyTelemetryCheck()
        self.config = config or ShellyTelemetryConfig()

    @property
    def name(self) -> str:
        return "shelly_telemetry"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        """Return the Shelly telemetry plugin manifest."""
        return PluginManifest(
            name="shelly_telemetry",
            version="0.1.0",
            description=(
                "Shelly power telemetry freshness plugin through Home Assistant."
            ),
        )

    def register(self, context: PluginContext) -> None:
        """Register the plugin in the Ohana-Agent context."""
        del context
        self._state = PluginState.REGISTERED

    def execute(self, **kwargs: Any) -> ObserverResult:
        """Check one configured Shelly device through the common plugin API."""
        from observer.observer_result import ObserverResult

        device_name = kwargs.get("device_name")
        power_entity_id = kwargs.get("power_entity_id")
        energy_entity_id = kwargs.get("energy_entity_id")

        if not isinstance(device_name, str) or not device_name.strip():
            raise ValueError(
                "ShellyTelemetryPlugin.execute() requires a non-empty "
                "'device_name' argument."
            )

        if not isinstance(power_entity_id, str) or not power_entity_id.strip():
            raise ValueError(
                "ShellyTelemetryPlugin.execute() requires a non-empty "
                "'power_entity_id' argument."
            )

        if energy_entity_id is not None and (
            not isinstance(energy_entity_id, str) or not energy_entity_id.strip()
        ):
            raise ValueError(
                "ShellyTelemetryPlugin.execute() requires 'energy_entity_id' "
                "to be null or non-empty."
            )

        started_at = perf_counter()
        result = self._check.check(
            device_name.strip(),
            power_entity_id.strip(),
            energy_entity_id=(
                energy_entity_id.strip() if isinstance(energy_entity_id, str) else None
            ),
            home_assistant_url=self.config.home_assistant_url,
            access_token=self.config.access_token,
            access_token_environment_variable=(
                self.config.access_token_environment_variable
            ),
            maximum_age_seconds=self.config.maximum_age_seconds,
            timeout=self.config.timeout,
            retries=self.config.retries,
            verify_tls=self.config.verify_tls,
        )
        elapsed_ms = (perf_counter() - started_at) * 1000
        message = (
            f"Shelly telemetry for {result.device_name} is fresh; "
            f"power is {result.power.value:g} {result.power.unit or ''}.".rstrip()
            if result.healthy and result.power.value is not None
            else result.error
            or f"Shelly telemetry for {result.device_name} is unavailable."
        )

        return ObserverResult(
            success=result.healthy,
            latency=elapsed_ms,
            message=message,
            check="shelly.telemetry.freshness",
            description=(
                "Check that Home Assistant still receives Shelly power telemetry."
            ),
            metadata={
                "device_name": result.device_name,
                "power": self._value_metadata(result.power),
                "energy": (
                    self._value_metadata(result.energy)
                    if result.energy is not None
                    else None
                ),
                "maximum_age_seconds": self.config.maximum_age_seconds,
                "attempts": result.attempts,
                "home_assistant_url": self.config.home_assistant_url,
                "verify_tls": self.config.verify_tls,
                "error": result.error,
            },
        )

    def reconfigure(self, config: ShellyTelemetryConfig) -> None:
        """Replace Shelly devices and policy without recreating the plugin."""
        self.config = config

    @staticmethod
    def _value_metadata(value: ShellyTelemetryValue) -> dict[str, object | None]:
        return {
            "entity_id": value.entity_id,
            "value": value.value,
            "unit": value.unit,
            "reported_at": (
                value.reported_at.isoformat() if value.reported_at is not None else None
            ),
            "age_seconds": value.age_seconds,
        }
