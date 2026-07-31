"""Generic entity freshness check through Home Assistant."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from plugins.home_assistant_telemetry.home_assistant_telemetry_client import (
    HomeAssistantEntityState,
    HomeAssistantTelemetryClient,
)
from plugins.home_assistant_telemetry.home_assistant_telemetry_result import (
    HomeAssistantTelemetryCheckResult,
    HomeAssistantTelemetryValue,
)


class HomeAssistantTelemetryCheck:
    """Ensure Home Assistant still receives configured entity telemetry."""

    def __init__(self, client: HomeAssistantTelemetryClient | None = None) -> None:
        self._client = client or HomeAssistantTelemetryClient()

    def check(
        self,
        service_name: str,
        primary_entity_id: str,
        *,
        secondary_entity_id: str | None = None,
        home_assistant_url: str,
        access_token: str | None,
        access_token_environment_variable: str | None,
        maximum_age_seconds: int,
        timeout: float = 5.0,
        retries: int = 1,
        verify_tls: bool = True,
        now: datetime | None = None,
    ) -> HomeAssistantTelemetryCheckResult:
        """Read configured entities until telemetry is fresh or retries end."""
        if retries < 0:
            raise ValueError("retries must be greater than or equal to zero.")

        token = access_token

        if token is None and access_token_environment_variable is not None:
            token = os.getenv(access_token_environment_variable)

        empty_primary = HomeAssistantTelemetryValue(entity_id=primary_entity_id)

        if not token:
            return HomeAssistantTelemetryCheckResult(
                service_name=service_name,
                healthy=False,
                primary=empty_primary,
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
        last_result: HomeAssistantTelemetryCheckResult | None = None
        attempts = 0

        for _attempt in range(retries + 1):
            attempts += 1
            primary_state = self._client.query_entity(
                home_assistant_url,
                primary_entity_id,
                access_token=token,
                timeout=timeout,
                verify_tls=verify_tls,
            )
            primary, primary_error = self._validate_state(
                primary_state,
                current_time=current_time,
                maximum_age_seconds=maximum_age_seconds,
            )
            secondary = None
            secondary_error = None

            if secondary_entity_id is not None:
                secondary_state = self._client.query_entity(
                    home_assistant_url,
                    secondary_entity_id,
                    access_token=token,
                    timeout=timeout,
                    verify_tls=verify_tls,
                )
                secondary, secondary_error = self._validate_state(
                    secondary_state,
                    current_time=current_time,
                    maximum_age_seconds=maximum_age_seconds,
                )

            error = primary_error or secondary_error
            last_result = HomeAssistantTelemetryCheckResult(
                service_name=service_name,
                healthy=error is None,
                primary=primary,
                secondary=secondary,
                attempts=attempts,
                error=error,
            )

            if last_result.healthy:
                break

        if last_result is None:
            raise RuntimeError(
                "Home Assistant telemetry check did not execute any request."
            )

        return last_result

    @staticmethod
    def _validate_state(
        state: HomeAssistantEntityState,
        *,
        current_time: datetime,
        maximum_age_seconds: int,
    ) -> tuple[HomeAssistantTelemetryValue, str | None]:
        value = HomeAssistantTelemetryValue(entity_id=state.entity_id, unit=state.unit)

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
        validated = HomeAssistantTelemetryValue(
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
