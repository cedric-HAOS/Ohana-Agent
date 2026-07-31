"""Linky Téléinformation checks from Home Assistant or direct HTTP frames."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from plugins.teleinformation.teleinformation_client import (
    HomeAssistantEntityState,
    HomeAssistantTeleinformationClient,
)
from plugins.teleinformation.teleinformation_frame_store import (
    TeleinformationFrameStore,
)
from plugins.teleinformation.teleinformation_result import (
    TeleinformationCheckResult,
    TeleinformationTariff,
    TeleinformationValue,
)

_TARIFF_TRANSITION_GRACE_SECONDS = 30

_TARIFFS = {
    1: TeleinformationTariff(1, "Bleue", "HC", "HC Bleue", "blue_off_peak", "EASF01"),
    2: TeleinformationTariff(2, "Bleue", "HP", "HP Bleue", "blue_peak", "EASF02"),
    3: TeleinformationTariff(3, "Blanc", "HC", "HC Blanc", "white_off_peak", "EASF03"),
    4: TeleinformationTariff(4, "Blanc", "HP", "HP Blanc", "white_peak", "EASF04"),
    5: TeleinformationTariff(5, "Rouge", "HC", "HC Rouge", "red_off_peak", "EASF05"),
    6: TeleinformationTariff(6, "Rouge", "HP", "HP Rouge", "red_peak", "EASF06"),
}

_INDEX_LABELS = {
    "blue_off_peak": "EASF01",
    "blue_peak": "EASF02",
    "white_off_peak": "EASF03",
    "white_peak": "EASF04",
    "red_off_peak": "EASF05",
    "red_peak": "EASF06",
}


class TeleinformationCheck:
    """Validate Linky data received through either supported transport."""

    def __init__(
        self,
        client: HomeAssistantTeleinformationClient | None = None,
        frame_store: TeleinformationFrameStore | None = None,
    ) -> None:
        self._client = client or HomeAssistantTeleinformationClient()
        self._frame_store = frame_store or TeleinformationFrameStore()

    @property
    def frame_store(self) -> TeleinformationFrameStore:
        return self._frame_store

    def check_direct(
        self,
        meter_name: str,
        *,
        source_id: str,
        meter_id: str,
        maximum_age_seconds: int,
        now: datetime | None = None,
    ) -> TeleinformationCheckResult:
        """Validate the latest frame pushed directly by teleinfo2mqtt."""
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        frame = self._frame_store.get(source=source_id, meter_id=meter_id)
        empty_power = TeleinformationValue(entity_id="SINSTS")
        empty_tariff = TeleinformationValue(entity_id="NTARF")

        if frame is None:
            return TeleinformationCheckResult(
                meter_name=meter_name,
                healthy=False,
                apparent_power=empty_power,
                tariff_value=empty_tariff,
                error=(
                    f"Aucune trame directe reçue de {source_id} pour le compteur "
                    f"{meter_id}."
                ),
                mode="direct_http",
                source_id=source_id,
                meter_id=meter_id,
            )

        age_seconds = max(0.0, (current_time - frame.received_at).total_seconds())
        power, power_error = self._direct_numeric_value(
            frame.values,
            "SINSTS",
            unit="VA",
            reported_at=frame.received_at,
            age_seconds=age_seconds,
        )
        tariff_value, tariff_error = self._direct_numeric_value(
            frame.values,
            "NTARF",
            unit=None,
            reported_at=frame.received_at,
            age_seconds=age_seconds,
        )
        tariff, tariff_mapping_error = self._resolve_tariff(tariff_value)
        indexes: dict[str, TeleinformationValue] = {}

        for index_key, label in _INDEX_LABELS.items():
            value, _error = self._direct_numeric_value(
                frame.values,
                label,
                unit="Wh",
                reported_at=frame.received_at,
                age_seconds=age_seconds,
                required=False,
            )
            if value.value is not None:
                indexes[index_key] = value

        active_index = indexes.get(tariff.index_key) if tariff is not None else None
        active_index_error = None

        if tariff is not None and active_index is None:
            active_index_error = (
                f"La trame ne contient pas l'index actif {tariff.index_label} "
                f"pour la période {tariff.label}."
            )

        freshness_error = None
        if age_seconds > maximum_age_seconds:
            freshness_error = (
                f"Aucune trame téléinformation reçue depuis {age_seconds:.0f} secondes."
            )

        error = (
            freshness_error
            or power_error
            or tariff_error
            or tariff_mapping_error
            or active_index_error
        )
        return TeleinformationCheckResult(
            meter_name=meter_name,
            healthy=error is None,
            apparent_power=power,
            tariff_value=tariff_value,
            tariff=tariff,
            indexes=indexes,
            active_index=active_index,
            attempts=1,
            error=error,
            mode="direct_http",
            source_id=source_id,
            meter_id=meter_id,
        )

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
        """Compatibility check through Home Assistant for existing deployments."""
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
                mode="home_assistant",
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
                require_freshness=False,
            )
            tariff, tariff_mapping_error = self._resolve_tariff(tariff_value)
            indexes: dict[str, TeleinformationValue] = {}
            active_index_error = None

            for index_key, entity_id in configured_indexes.items():
                state = self._query(
                    home_assistant_url,
                    entity_id,
                    token=token,
                    timeout=timeout,
                    verify_tls=verify_tls,
                )
                is_active_index = tariff is not None and index_key == tariff.index_key
                value, error = self._validate_numeric_state(
                    state,
                    current_time=current_time,
                    maximum_age_seconds=maximum_age_seconds,
                    require_freshness=is_active_index,
                )
                indexes[index_key] = value
                if (
                    is_active_index
                    and active_index_error is None
                    and error is not None
                    and not self._is_expected_tariff_transition(
                        tariff_value,
                        value,
                        maximum_age_seconds=maximum_age_seconds,
                    )
                ):
                    active_index_error = error

            active_index = indexes.get(tariff.index_key) if tariff is not None else None
            error = (
                power_error
                or tariff_error
                or tariff_mapping_error
                or active_index_error
            )
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
                mode="home_assistant",
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
    def _direct_numeric_value(
        values: dict[str, float | int | str],
        label: str,
        *,
        unit: str | None,
        reported_at: datetime,
        age_seconds: float,
        required: bool = True,
    ) -> tuple[TeleinformationValue, str | None]:
        raw_value = values.get(label)
        empty = TeleinformationValue(entity_id=label, unit=unit)
        if raw_value is None:
            return empty, (f"La trame ne contient pas {label}." if required else None)
        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError):
            return empty, f"La valeur {label} n'est pas numérique."
        return (
            TeleinformationValue(
                entity_id=label,
                value=numeric_value,
                unit=unit,
                reported_at=reported_at,
                age_seconds=age_seconds,
            ),
            None,
        )

    @staticmethod
    def _is_expected_tariff_transition(
        tariff_value: TeleinformationValue,
        active_index: TeleinformationValue,
        *,
        maximum_age_seconds: int,
    ) -> bool:
        return (
            tariff_value.age_seconds is not None
            and tariff_value.age_seconds <= _TARIFF_TRANSITION_GRACE_SECONDS
            and active_index.value is not None
            and active_index.age_seconds is not None
            and active_index.age_seconds > maximum_age_seconds
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
                (
                    f"Entity {state.entity_id} has not reported for "
                    f"{age_seconds:.0f} seconds."
                ),
            )
        return validated, None
