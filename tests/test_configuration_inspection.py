"""Configuration evidence is useful without exposing credentials or private paths."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from ohana_agent.tsunade.configuration_inspection import (
    _remote,
    addon_facts,
    configured_http_target,
    local_mqtt_configuration,
    safe_endpoint,
)


@pytest.mark.parametrize("node", ["infra-01", "ha-01", "zwave-01", "linky-01"])
@pytest.mark.parametrize("enabled", [True, False])
def test_http_target_reuses_only_selected_enabled_supervisor(node, enabled):
    target_id = "ha-01" if node == "infra-01" else node
    config = SimpleNamespace(
        targets=[
            SimpleNamespace(
                id=target_id, enabled=enabled, url="http://configured.test:8123"
            ),
            SimpleNamespace(id="unrelated", enabled=True, url="http://other.test"),
        ]
    )
    assert configured_http_target(config, node) == (
        (f"supervisor-http:{target_id}", "http://configured.test:8123")
        if enabled
        else None
    )
    assert configured_http_target(config, "unknown") is None


@pytest.mark.parametrize(
    "node_id,target_id,slug",
    [
        ("infra-01", "ha-01", "core_mosquitto"),
        ("ha-01", "ha-01", "core_mosquitto"),
        ("linky-01", "linky-01", "local_teleinfo2mqtt"),
        ("zwave-01", "zwave-01", "core_zwave_js"),
        ("zwave-01", "zwave-01", "a0d7b954_zwavejs2mqtt"),
    ],
)
def test_supervisor_inspection_uses_only_fixed_get_requests(
    monkeypatch, node_id, target_id, slug
):
    requests = []

    class Socket:
        async def __aenter__(self):
            self.replies = iter(
                [
                    {"type": "auth_required"},
                    {"type": "auth_ok"},
                    {
                        "success": True,
                        "result": {
                            "addons": [
                                {"slug": "unrelated_addon"},
                                {"slug": "core_mosquitto"}
                                if node_id == "zwave-01"
                                else {"slug": "core_zwave_js"},
                                {"slug": slug},
                            ]
                        },
                    },
                    {"success": False},
                    {
                        "success": True,
                        "result": {
                            "slug": slug,
                            "state": "started",
                            "options": {
                                "network_key": "secret",
                                "s2_access_control_key": "secret",
                            },
                        },
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
        id=target_id, enabled=True, token="secret", url="https://ha", verify_tls=True
    )
    result = asyncio.run(_remote(SimpleNamespace(targets=[target]), node_id))
    assert result["hardware_available"] is False
    assert result["addons"][0]["state"] == "started"
    assert result["addons"][0]["addon"] == slug
    assert result["addon_selection"]["status"] == "matched"
    assert result["origin"] == target_id + " / Supervisor"
    assert "secret" not in json.dumps(result)
    assert requests[0] == {"type": "auth", "access_token": "secret"}
    assert [r["endpoint"] for r in requests[1:]] == [
        "/addons",
        "/hardware/info",
        f"/addons/{slug}/info",
        f"/addons/{slug}/stats",
        "/core/info",
    ]
    assert all(r["method"] == "get" for r in requests[1:])


@pytest.mark.parametrize("listing_available", [True, False])
def test_missing_zwave_addon_is_not_reported_as_service_failure(
    monkeypatch, listing_available
):
    requests = []

    class Socket:
        async def __aenter__(self):
            self.replies = iter(
                [
                    {"type": "auth_required"},
                    {"type": "auth_ok"},
                    {
                        "success": listing_available,
                        "result": {"addons": [{"slug": "core_mosquitto"}]},
                    },
                    {"success": True, "result": {}},
                    {"success": True, "result": {"state": "running"}},
                ]
            )
            return self

        async def __aexit__(self, *_args):
            pass

        async def receive_json(self):
            return next(self.replies)

        async def send_json(self, data):
            requests.append(data)

    class Session(Socket):
        def __init__(self, **_kwargs):
            pass

        def ws_connect(self, *_args, **_kwargs):
            return Socket()

    monkeypatch.setattr(
        "ohana_agent.tsunade.configuration_inspection.aiohttp.ClientSession", Session
    )
    target = SimpleNamespace(
        id="zwave-01",
        enabled=True,
        token="secret",
        url="https://zwave",
        verify_tls=True,
    )
    result = asyncio.run(_remote(SimpleNamespace(targets=[target]), "zwave-01"))
    assert result["addons"] == []
    assert result["addon_selection"]["status"] == (
        "no_match" if listing_available else "unavailable"
    )
    assert result["core"]["state"] == "running"
    assert [r["endpoint"] for r in requests[1:]] == [
        "/addons",
        "/hardware/info",
        "/core/info",
    ]
    assert "secret" not in json.dumps(result)


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
