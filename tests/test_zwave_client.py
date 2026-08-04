"""Tests for Z-Wave endpoint protocol selection."""

import pytest

from plugins.zwave.zwave_client import ZWaveHealthClient
from plugins.zwave.zwave_result import ZWaveHealthResult


def test_zwave_client_uses_websocket_query() -> None:
    calls: list[tuple[str, float, bool]] = []

    async def query(url: str, timeout: float, verify_tls: bool) -> ZWaveHealthResult:
        calls.append((url, timeout, verify_tls))
        return ZWaveHealthResult(url=url, healthy=True, node_count=8)

    result = ZWaveHealthClient(websocket_query=query).query(
        "ws://192.168.1.11:3000",
        timeout=4.0,
        verify_tls=False,
    )

    assert result.healthy is True
    assert result.node_count == 8
    assert calls == [("ws://192.168.1.11:3000", 4.0, False)]


def test_zwave_client_rejects_unknown_scheme() -> None:
    result = ZWaveHealthClient().query("tcp://192.168.1.11:3000")

    assert result.healthy is False
    assert result.error == "Unsupported Z-Wave endpoint scheme: tcp."


def test_zwave_client_reports_ready_websocket_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The WebSocket probe must wait for the complete Z-Wave driver state."""
    import asyncio
    import sys
    from types import ModuleType, SimpleNamespace

    class FakeClient:
        def __init__(self, url, session, **kwargs) -> None:
            del session, kwargs
            self.url = url
            self.connected = False
            self.version = SimpleNamespace(
                server_version="3.4.0",
                driver_version="15.0.0",
                home_id=0x12345678,
            )
            self.driver = None

        async def connect(self) -> None:
            self.connected = True

        async def listen(self, driver_ready: asyncio.Event) -> None:
            self.driver = SimpleNamespace(
                controller=SimpleNamespace(
                    nodes={
                        1: SimpleNamespace(
                            node_id=1,
                            is_controller_node=True,
                        ),
                        2: SimpleNamespace(
                            node_id=2,
                            is_controller_node=False,
                            status=SimpleNamespace(name="ASLEEP"),
                            ready=True,
                            name="Detecteur entree",
                            label="Door sensor",
                            location="Entree",
                            manufacturer="Aeotec",
                            product_id=2,
                            product_type=1,
                            firmware_version="1.2",
                            can_sleep=True,
                            last_seen=None,
                        ),
                    },
                ),
            )
            driver_ready.set()
            await asyncio.Event().wait()

        async def disconnect(self) -> None:
            self.connected = False

    package = ModuleType("zwave_js_server")
    module = ModuleType("zwave_js_server.client")
    module.Client = FakeClient
    package.client = module
    monkeypatch.setitem(sys.modules, "zwave_js_server", package)
    monkeypatch.setitem(sys.modules, "zwave_js_server.client", module)

    result = asyncio.run(
        ZWaveHealthClient()._query_websocket(
            "ws://192.168.1.11:3000",
            timeout=1.0,
            verify_tls=True,
        )
    )

    assert result.healthy is True
    assert result.response == "Z-Wave JS driver ready"
    assert result.server_version == "3.4.0"
    assert result.driver_version == "15.0.0"
    assert result.home_id == str(0x12345678)
    assert result.node_count == 2
    assert result.discovery_complete is True
    assert len(result.nodes) == 1
    assert result.nodes[0].node_id == 2
    assert result.nodes[0].status == "asleep"
    assert result.nodes[0].alive is True
    assert result.nodes[0].name == "Detecteur entree"
    assert result.nodes[0].can_sleep is True
