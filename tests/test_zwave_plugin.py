"""Tests for the Z-Wave observation plugin."""

import pytest

from plugins.zwave.zwave_config import ZWaveConfig
from plugins.zwave.zwave_plugin import ZWavePlugin
from plugins.zwave.zwave_result import ZWaveHealthResult, ZWaveNodeResult


class FakeZWaveCheck:
    def __init__(self, result: ZWaveHealthResult) -> None:
        self.result = result
        self.calls: list[tuple[str, float, int, bool]] = []

    def check(
        self,
        url: str,
        *,
        timeout: float,
        retries: int,
        verify_tls: bool,
    ) -> ZWaveHealthResult:
        self.calls.append((url, timeout, retries, verify_tls))
        return self.result


def test_zwave_plugin_returns_observer_result() -> None:
    check = FakeZWaveCheck(
        ZWaveHealthResult(
            url="ws://192.168.1.11:3000",
            healthy=True,
            response="Z-Wave JS driver ready",
            server_version="3.2.0",
            driver_version="15.0.0",
            home_id="0x12345678",
            node_count=12,
            nodes=(
                ZWaveNodeResult(
                    node_id=7,
                    status="dead",
                    name="Prise garage",
                ),
            ),
            discovery_complete=True,
        )
    )
    plugin = ZWavePlugin(
        check=check,
        config=ZWaveConfig(timeout=2.0, retries=2, verify_tls=False),
    )

    result = plugin.execute(
        url="ws://192.168.1.11:3000",
    )

    assert result.success is True
    assert result.check == "zwave.status"
    assert result.metadata["node_count"] == 12
    assert result.metadata["driver_version"] == "15.0.0"
    assert result.metadata["discovery_complete"] is True
    assert result.metadata["nodes"] == [
        {
            "node_id": 7,
            "status": "dead",
            "alive": False,
            "ready": False,
            "name": "Prise garage",
            "label": None,
            "location": None,
            "manufacturer": None,
            "product_id": None,
            "product_type": None,
            "firmware_version": None,
            "can_sleep": False,
            "last_seen": None,
        }
    ]
    assert check.calls == [("ws://192.168.1.11:3000", 2.0, 2, False)]


def test_zwave_plugin_requires_endpoint_url() -> None:
    with pytest.raises(ValueError, match="url"):
        ZWavePlugin().execute(url="")
