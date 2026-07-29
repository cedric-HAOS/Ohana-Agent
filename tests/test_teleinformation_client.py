"""Tests for the Home Assistant client used by Téléinformation."""

import json
from urllib.request import Request

from plugins.teleinformation.teleinformation_client import (
    HomeAssistantTeleinformationClient,
)


class FakeHTTPResponse:
    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        payload = {
            "entity_id": "sensor.teleinfo_041964385922_sinsts",
            "state": "1392",
            "last_reported": "2026-07-29T10:00:00+00:00",
            "attributes": {"unit_of_measurement": "VA"},
        }
        return json.dumps(payload).encode("utf-8")[:size]


def test_teleinformation_client_reads_linky_state(monkeypatch) -> None:
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
        "plugins.teleinformation.teleinformation_client.urlopen",
        fake_urlopen,
    )

    state = HomeAssistantTeleinformationClient().query_entity(
        "http://ha-green:8123",
        "sensor.teleinfo_041964385922_sinsts",
        access_token="secret",
    )

    assert state.state == "1392"
    assert state.unit == "VA"
    assert calls[0].get_header("Authorization") == "Bearer secret"
