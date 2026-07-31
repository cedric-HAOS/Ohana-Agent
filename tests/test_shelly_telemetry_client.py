"""Tests for the Home Assistant REST client used by Shelly telemetry."""

import json
from urllib.request import Request

from plugins.home_assistant_telemetry.home_assistant_telemetry_client import (
    HomeAssistantTelemetryClient,
)


class FakeHTTPResponse:
    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        payload = {
            "entity_id": "sensor.shelly_power",
            "state": "12.4",
            "last_reported": "2026-07-27T18:00:00+00:00",
            "last_updated": "2026-07-27T17:50:00+00:00",
            "attributes": {"unit_of_measurement": "W"},
        }
        return json.dumps(payload).encode("utf-8")[:size]


def test_home_assistant_client_prefers_last_reported(monkeypatch) -> None:
    calls: list[Request] = []

    def fake_urlopen(
        request: Request,
        *,
        timeout: float,
        context: object,
    ) -> FakeHTTPResponse:
        del timeout, context
        calls.append(request)
        return FakeHTTPResponse()

    monkeypatch.setattr(
        "plugins.home_assistant_telemetry.home_assistant_telemetry_client.urlopen",
        fake_urlopen,
    )

    state = HomeAssistantTelemetryClient().query_entity(
        "http://ha-green:8123",
        "sensor.shelly_power",
        access_token="secret",
    )

    assert state.state == "12.4"
    assert state.reported_at == "2026-07-27T18:00:00+00:00"
    assert state.unit == "W"
    assert calls[0].get_header("Authorization") == "Bearer secret"
