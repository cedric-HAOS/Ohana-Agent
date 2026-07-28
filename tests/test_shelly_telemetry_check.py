"""Tests for Shelly telemetry freshness checks."""

from datetime import UTC, datetime

from plugins.shelly_telemetry.shelly_telemetry_check import ShellyTelemetryCheck
from plugins.shelly_telemetry.shelly_telemetry_client import HomeAssistantEntityState


class FakeHomeAssistantClient:
    def __init__(self, states: list[HomeAssistantEntityState]) -> None:
        self.states = states
        self.calls: list[str] = []

    def query_entity(
        self,
        base_url: str,
        entity_id: str,
        *,
        access_token: str,
        timeout: float,
        verify_tls: bool,
    ) -> HomeAssistantEntityState:
        del base_url, access_token, timeout, verify_tls
        self.calls.append(entity_id)
        return self.states[len(self.calls) - 1]


def test_shelly_telemetry_accepts_zero_watt_fresh_report() -> None:
    now = datetime(2026, 7, 27, 18, 0, tzinfo=UTC)
    client = FakeHomeAssistantClient(
        [
            HomeAssistantEntityState(
                entity_id="sensor.shelly_power",
                state="0",
                reported_at="2026-07-27T17:59:30+00:00",
                unit="W",
            )
        ]
    )

    result = ShellyTelemetryCheck(client=client).check(
        "Cuisine",
        "sensor.shelly_power",
        home_assistant_url="http://ha-green:8123",
        access_token="secret",
        access_token_environment_variable=None,
        maximum_age_seconds=300,
        now=now,
    )

    assert result.healthy is True
    assert result.power.value == 0.0
    assert result.power.age_seconds == 30.0


def test_shelly_telemetry_rejects_stale_report() -> None:
    now = datetime(2026, 7, 27, 18, 0, tzinfo=UTC)
    client = FakeHomeAssistantClient(
        [
            HomeAssistantEntityState(
                entity_id="sensor.shelly_power",
                state="42.5",
                reported_at="2026-07-27T17:40:00+00:00",
                unit="W",
            )
        ]
    )

    result = ShellyTelemetryCheck(client=client).check(
        "Cuisine",
        "sensor.shelly_power",
        home_assistant_url="http://ha-green:8123",
        access_token="secret",
        access_token_environment_variable=None,
        maximum_age_seconds=300,
        retries=0,
        now=now,
    )

    assert result.healthy is False
    assert "has not reported" in (result.error or "")
