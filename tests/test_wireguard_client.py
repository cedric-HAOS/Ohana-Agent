"""Tests for the authenticated Freebox WireGuard client."""

import json
from typing import Any
from urllib.request import Request

from plugins.wireguard.wireguard_client import FreeboxWireGuardClient


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._payload[:size]


def test_freebox_wireguard_client_opens_session_and_reads_vpn_server(
    monkeypatch,
) -> None:
    responses = iter(
        [
            {"api_version": "15.0", "api_base_url": "/api/"},
            {"success": True, "result": {"challenge": "challenge"}},
            {"success": True, "result": {"session_token": "session"}},
            {
                "success": True,
                "result": [
                    {
                        "name": "wireguard",
                        "state": "started",
                        "connection_count": 2,
                        "auth_connection_count": 1,
                    }
                ],
            },
        ]
    )
    calls: list[Request] = []

    def fake_urlopen(
        request: Request,
        *,
        timeout: float,
        context: object,
    ) -> FakeHTTPResponse:
        del timeout, context
        calls.append(request)
        return FakeHTTPResponse(next(responses))

    monkeypatch.setattr(
        "plugins.wireguard.wireguard_client.urlopen",
        fake_urlopen,
    )

    result = FreeboxWireGuardClient().query(
        "http://192.168.1.1",
        app_id="fr.ohana.agent",
        app_version="1.7.3",
        app_token="secret",
    )

    assert result.success is True
    assert result.state == "started"
    assert result.connection_count == 2
    assert [request.full_url for request in calls] == [
        "http://192.168.1.1/api_version",
        "http://192.168.1.1/api/v15/login/",
        "http://192.168.1.1/api/v15/login/session/",
        "http://192.168.1.1/api/v15/vpn/",
    ]
    assert calls[-1].get_header("X-fbx-app-auth") == "session"


def test_freebox_wireguard_client_requires_app_token() -> None:
    result = FreeboxWireGuardClient().query(
        "http://192.168.1.1",
        app_id="fr.ohana.agent",
        app_version="1.7.3",
        app_token=None,
    )

    assert result.success is False
    assert "app_token" in (result.error or "")
