"""Shelly telemetry freshness check through Home Assistant."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from plugins.shelly_telemetry.shelly_telemetry_client import (
    HomeAssistantEntityState,
    HomeAssistantTelemetryClient,
)
from plugins.shelly_telemetry.shelly_telemetry_result import (
    ShellyTelemetryCheckResult,
    ShellyTelemetryValue,
)


class ShellyTelemetryCheck:
    """Ensure Home Assistant still receives Shelly power telemetry."""

    def __init__(self, client: HomeAssistantTelemetryClient | None = None) -> None:
        self._client = client or HomeAssistantTelemetryClient()

    def check(
        self,
        device_name: str,
        power_entity_id: str,
        *,
        energy_entity_id: str | None = None,
        home_assistant_url: str,
        access_token: str | None,
        access_token_environment_variable: str | None,
        maximum_age_seconds: int,
        timeout: float = 5.0,
        retries: int = 1,
        verify_tls: bool = True,
        now: datetime | None = None,
    ) -> ShellyTelemetryCheckResult:
        """Read configured sensors until telemetry is fresh or retries end."""
        if retries < 0:
            raise ValueError("retries must be greater than or equal to zero.")

        token = access_token

        if token is None and access_token_environment_variable is not None:
            token = os.getenv(access_token_environment_variable)

        empty_power = ShellyTelemetryValue(entity_id=power_entity_id)

        if not token:
            return ShellyTelemetryCheckResult(
                device_name=device_name,
                healthy=False,
                power=empty_power,
                error=(
                    "The Home Assistant access token is not configured"
                    + (
                        f" in {access_token_environment_variable}."
                        if access_token_environment_variable
                        else "."
                    )
                ),
            )

        current_time = now or datetime.now(UTC)
        last_result: ShellyTelemetryCheckResult | None = None
        attempts = 0

        for _attempt in range(retries + 1):
            attempts += 1
            power_state = self._client.query_entity(
                home_assistant_url,
                power_entity_id,
                access_token=token,
                timeout=timeout,
                verify_tls=verify_tls,
            )
            power, power_error = self._validate_state(
                power_state,
                current_time=current_time,
                maximum_age_seconds=maximum_age_seconds,
            )
            energy = None
            energy_error = None

            if energy_entity_id is not None:
                energy_state = self._client.query_entity(
                    home_assistant_url,
                    energy_entity_id,
                    access_token=token,
                    timeout=timeout,
                    verify_tls=verify_tls,
                )
                energy, energy_error = self._validate_state(
                    energy_state,
                    current_time=current_time,
                    maximum_age_seconds=maximum_age_seconds,
                )

            error = power_error or energy_error
            last_result = ShellyTelemetryCheckResult(
                device_name=device_name,
                healthy=error is None,
                power=power,
                energy=energy,
                attempts=attempts,
                error=error,
            )

            if last_result.healthy:
                break

        if last_result is None:
            raise RuntimeError("Shelly telemetry check did not execute any request.")

        return last_result

    @staticmethod
    def _validate_state(
        state: HomeAssistantEntityState,
        *,
        current_time: datetime,
        maximum_age_seconds: int,
    ) -> tuple[ShellyTelemetryValue, str | None]:
        value = ShellyTelemetryValue(entity_id=state.entity_id, unit=state.unit)

        if state.error:
            return value, state.error

        if state.state in {None, "unknown", "unavailable"}:
            return value, f"Entity {state.entity_id} is {state.state or 'invalid'}."

        try:
            numeric_value = float(state.state)
        except ValueError:
            return value, f"Entity {state.entity_id} is not numeric."

        if not state.reported_at:
            return value, f"Entity {state.entity_id} has no report timestamp."

        try:
            reported_at = datetime.fromisoformat(
                state.reported_at.replace("Z", "+00:00")
            )
        except ValueError:
            return value, f"Entity {state.entity_id} has an invalid timestamp."

        if reported_at.tzinfo is None:
            reported_at = reported_at.replace(tzinfo=UTC)

        age_seconds = max(
            0.0,
            (current_time - reported_at.astimezone(UTC)).total_seconds(),
        )
        validated = ShellyTelemetryValue(
            entity_id=state.entity_id,
            value=numeric_value,
            unit=state.unit,
            reported_at=reported_at,
            age_seconds=age_seconds,
        )

        if age_seconds > maximum_age_seconds:
            return (
                validated,
                f"Entity {state.entity_id} has not reported for "
                f"{age_seconds:.0f} seconds.",
            )

        return validated, None
