"""Configuration evidence is useful without exposing credentials or private paths."""

import asyncio
import json
from types import SimpleNamespace

from ohana_agent.tsunade.configuration_inspection import (
    _remote,
    addon_facts,
    local_mqtt_configuration,
    safe_endpoint,
)


def test_supervisor_inspection_uses_only_fixed_get_requests(monkeypatch):
    requests = []

    class Socket:
        async def __aenter__(self):
            self.replies = iter(
                [
                    {"type": "auth_required"},
                    {"type": "auth_ok"},
                    {
                        "success": True,
                        "result": {"addons": [{"slug": "core_mosquitto"}]},
                    },
                    {"success": False},
                    {
                        "success": True,
                        "result": {"slug": "core_mosquitto", "state": "started"},
                    },
                    {"success": True, "result": {"cpu_percent": 0.1}},
                    {"success": True, "result": {"version": "2026.9.1"}},
                ]
            )
            return self

        async def __aexit__(self, *_args):
            pass

        async def receive_json(self):
            return next(self.replies)

        async def send_json(self, data):
            requests.append(data)

    class Session:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        def ws_connect(self, url, **_kwargs):
            assert url == "wss://ha/api/websocket"
            return Socket()

    monkeypatch.setattr(
        "ohana_agent.tsunade.configuration_inspection.aiohttp.ClientSession", Session
    )
    target = SimpleNamespace(
        id="ha-01", enabled=True, token="secret", url="https://ha", verify_tls=True
    )
    result = asyncio.run(_remote(SimpleNamespace(targets=[target]), "infra-01"))
    assert result["hardware_available"] is False
    assert result["addons"][0]["state"] == "started"
    assert "secret" not in json.dumps(result)
    assert requests[0] == {"type": "auth", "access_token": "secret"}
    assert [r["endpoint"] for r in requests[1:]] == [
        "/addons",
        "/hardware/info",
        "/addons/core_mosquitto/info",
        "/addons/core_mosquitto/stats",
        "/core/info",
    ]
    assert all(r["method"] == "get" for r in requests[1:])


def test_mqtt_configuration_exports_presence_not_credentials():
    state = SimpleNamespace(
        enabled=True,
        status="running",
        configuration={
            "authentication": {
                "username": "private-user",
                "password": "private-password",
                "password_configured": True,
            },
            "tls": {"enabled": True, "insecure": False},
            "qos": 1,
        },
    )
    data = local_mqtt_configuration(SimpleNamespace(read=lambda name: state))
    assert data["password_configured"]
    assert data["username_configured"]
    assert "private" not in json.dumps(data)


def test_remote_addon_configuration_includes_serial_and_safe_mqtt_endpoint():
    info = {
        "slug": "teleinfo",
        "state": "started",
        "uart": True,
        "options": {
            "SERIAL": "/dev/serial0",
            "MQTT_URL": "mqtt://alice:secret@broker:1883/path?key=secret",
            "MQTT_PASSWORD": "secret",
            "OHANA_TOKEN": "secret",
            "OHANA_URL": "http://agent:8770/private?token=secret",
            "logins": [{"username": "private", "password": "secret"}],
            "customize": {"active": False},
        },
    }
    hardware = {
        "devices": [
            {"dev_path": "/dev/ttyAMA0", "children": [{"dev_path": "/dev/serial0"}]}
        ]
    }
    result = addon_facts(info, hardware, {"cpu_percent": 3})
    assert result["serial"]["listed_by_supervisor"] is True
    assert result["serial"]["uart_access"] is True
    assert result["configuration"]["MQTT_URL"]["host"] == "broker"
    assert result["configuration"]["MQTT_URL"]["credentials_embedded"] is True
    assert result["runtime_stats"]["cpu_percent"] == 3
    assert result["mqtt_login_count"] == 1
    for secret in ("alice", "secret", "private", "token="):
        assert secret not in json.dumps(result)


def test_endpoint_drops_url_path_and_query():
    assert safe_endpoint("http://host:8123/api?token=private") == {
        "configured": True,
        "scheme": "http",
        "host": "host",
        "port": 8123,
        "credentials_embedded": False,
    }
