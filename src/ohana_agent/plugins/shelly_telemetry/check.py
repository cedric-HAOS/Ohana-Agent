"""Compatibility wrapper for the former Shelly telemetry check."""

from ohana_agent.plugins.home_assistant_telemetry.check import (
    HomeAssistantTelemetryCheck,
)
from ohana_agent.plugins.shelly_telemetry.result import (
    ShellyTelemetryCheckResult,
)


class ShellyTelemetryCheck(HomeAssistantTelemetryCheck):
    """Expose the legacy call and result names during migration."""

    def check(
        self,
        device_name: str,
        power_entity_id: str,
        *,
        energy_entity_id: str | None = None,
        **kwargs: object,
    ) -> ShellyTelemetryCheckResult:
        result = super().check(
            device_name,
            power_entity_id,
            secondary_entity_id=energy_entity_id,
            **kwargs,
        )
        return ShellyTelemetryCheckResult(
            device_name=result.service_name,
            healthy=result.healthy,
            power=result.primary,
            energy=result.secondary,
            attempts=result.attempts,
            error=result.error,
        )
