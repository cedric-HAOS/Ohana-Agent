"""Linky Téléinformation freshness check through Home Assistant."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from plugins.teleinformation.teleinformation_client import (
    HomeAssistantEntityState,
    HomeAssistantTeleinformationClient,
)
from plugins.teleinformation.teleinformation_result import (
    TeleinformationCheckResult,
    TeleinformationTariff,
    TeleinformationValue,
)

_TARIFFS = {
    1: TeleinformationTariff(1, "Bleue", "HC", "HC Bleue", "blue_off_peak"),
    2: TeleinformationTariff(2, "Bleue", "HP", "HP Bleue", "blue_peak"),
    3: TeleinformationTariff(3, "Blanc", "HC", "HC Blanc", "white_off_peak"),
    4: TeleinformationTariff(4, "Blanc", "HP", "HP Blanc", "white_peak"),
    5: TeleinformationTariff(5, "Rouge", "HC", "HC Rouge", "red_off_peak"),
    6: TeleinformationTariff(6, "Rouge", "HP", "HP Rouge", "red_peak"),
}


class TeleinformationCheck:
    """Ensure Home Assistant still receives valid Linky data."""

    def __init__(
        self,
        client: HomeAssistantTeleinformationClient | None = None,
    ) -> None:
        self._client = client or HomeAssistantTeleinformationClient()

    def check(
        self,
        meter_name: str,
        apparent_power_entity_id: str,
        tariff_entity_id: str,
        *,
        index_entity_ids: dict[str, str] | None = None,
        home_assistant_url: str,
        access_token: str | None,
        access_token_environment_variable: str | None,
        maximum_age_seconds: int,
        timeout: float = 5.0,
        retries: int = 1,
        verify_tls: bool = True,
        now: datetime | None = None,
    ) -> TeleinformationCheckResult:
        """Read Linky entities until the primary telemetry is fresh."""
        if retries < 0:
            raise ValueError("retries must be greater than or equal to zero.")

        token = access_token

        if token is None and access_token_environment_variable is not None:
            token = os.getenv(access_token_environment_variable)

        empty_power = TeleinformationValue(entity_id=apparent_power_entity_id)
        empty_tariff = TeleinformationValue(entity_id=tariff_entity_id)

        if not token:
            return TeleinformationCheckResult(
                meter_name=meter_name,
                healthy=False,
                apparent_power=empty_power,
                tariff_value=empty_tariff,
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
        configured_indexes = dict(index_entity_ids or {})
        last_result: TeleinformationCheckResult | None = None
        attempts = 0

        for _attempt in range(retries + 1):
            attempts += 1
            power_state = self._query(
                home_assistant_url,
                apparent_power_entity_id,
                token=token,
                timeout=timeout,
                verify_tls=verify_tls,
            )
            apparent_power, power_error = self._validate_numeric_state(
                power_state,
                current_time=current_time,
                maximum_age_seconds=maximum_age_seconds,
                require_freshness=True,
            )
            tariff_state = self._query(
                home_assistant_url,
                tariff_entity_id,
                token=token,
                timeout=timeout,
                verify_tls=verify_tls,
            )
            tariff_value, tariff_error = self._validate_numeric_state(
                tariff_state,
                current_time=current_time,
                maximum_age_seconds=maximum_age_seconds,
                require_freshness=True,
            )
            tariff, tariff_mapping_error = self._resolve_tariff(tariff_value)
            indexes: dict[str, TeleinformationValue] = {}
            index_error = None

            for index_key, entity_id in configured_indexes.items():
                state = self._query(
                    home_assistant_url,
                    entity_id,
                    token=token,
                    timeout=timeout,
                    verify_tls=verify_tls,
                )
                value, error = self._validate_numeric_state(
                    state,
                    current_time=current_time,
                    maximum_age_seconds=maximum_age_seconds,
                    require_freshness=False,
                )
                indexes[index_key] = value

                if index_error is None and error is not None:
                    index_error = error

            active_index = indexes.get(tariff.index_key) if tariff is not None else None
            error = power_error or tariff_error or tariff_mapping_error or index_error
            last_result = TeleinformationCheckResult(
                meter_name=meter_name,
                healthy=error is None,
                apparent_power=apparent_power,
                tariff_value=tariff_value,
                tariff=tariff,
                indexes=indexes,
                active_index=active_index,
                attempts=attempts,
                error=error,
            )

            if last_result.healthy:
                break

        if last_result is None:
            raise RuntimeError("Téléinformation check did not execute any request.")

        return last_result

    def _query(
        self,
        base_url: str,
        entity_id: str,
        *,
        token: str,
        timeout: float,
        verify_tls: bool,
    ) -> HomeAssistantEntityState:
        return self._client.query_entity(
            base_url,
            entity_id,
            access_token=token,
            timeout=timeout,
            verify_tls=verify_tls,
        )

    @staticmethod
    def _resolve_tariff(
        value: TeleinformationValue,
    ) -> tuple[TeleinformationTariff | None, str | None]:
        if value.value is None:
            return None, None

        tariff_number = int(value.value)

        if value.value != tariff_number or tariff_number not in _TARIFFS:
            return None, f"Entity {value.entity_id} contains invalid NTARF value."

        return _TARIFFS[tariff_number], None

    @staticmethod
    def _validate_numeric_state(
        state: HomeAssistantEntityState,
        *,
        current_time: datetime,
        maximum_age_seconds: int,
        require_freshness: bool,
    ) -> tuple[TeleinformationValue, str | None]:
        value = TeleinformationValue(entity_id=state.entity_id, unit=state.unit)

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
        validated = TeleinformationValue(
            entity_id=state.entity_id,
            value=numeric_value,
            unit=state.unit,
            reported_at=reported_at,
            age_seconds=age_seconds,
        )

        if require_freshness and age_seconds > maximum_age_seconds:
            return (
                validated,
                f"Entity {state.entity_id} has not reported for "
                f"{age_seconds:.0f} seconds.",
            )

        return validated, None
