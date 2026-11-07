"""Tests for the Z-Wave observation plugin."""

from datetime import UTC, datetime

import pytest

from ohana_agent.plugins.zwave.config import ZWaveConfig
from ohana_agent.plugins.zwave.plugin import ZWavePlugin
from ohana_agent.plugins.zwave.result import ZWaveHealthResult, ZWaveNodeResult


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
            "last_seen_age_seconds": None,
            "silence_threshold_minutes": None,
            "silent": None,
        }
    ]
    assert check.calls == [("ws://192.168.1.11:3000", 2.0, 2, False)]


def test_zwave_plugin_requires_endpoint_url() -> None:
    with pytest.raises(ValueError, match="url"):
        ZWavePlugin().execute(url="")


def _silence_plugin(
    *nodes: ZWaveNodeResult,
    config: ZWaveConfig,
) -> ZWavePlugin:
    check = FakeZWaveCheck(
        ZWaveHealthResult(
            url="ws://zwave:3000",
            healthy=True,
            node_count=len(nodes),
            nodes=tuple(nodes),
            discovery_complete=True,
        )
    )
    return ZWavePlugin(
        check=check,
        config=config,
        clock=lambda: datetime(2026, 11, 7, 12, 0, tzinfo=UTC),
    )


def test_zwave_plugin_flags_node_silent_beyond_the_delay() -> None:
    plugin = _silence_plugin(
        ZWaveNodeResult(
            node_id=3,
            status="alive",
            last_seen="2026-11-07T11:00:00+01:00",
        ),
        ZWaveNodeResult(
            node_id=4,
            status="alive",
            last_seen="2026-11-07T12:30:00+01:00",
        ),
        config=ZWaveConfig(last_seen_alert_minutes=60),
    )

    silent_node, recent_node = plugin.execute(url="ws://zwave:3000").metadata["nodes"]

    assert silent_node["last_seen_age_seconds"] == 7200
    assert silent_node["silence_threshold_minutes"] == 60
    assert silent_node["silent"] is True
    assert recent_node["last_seen_age_seconds"] == 1800
    assert recent_node["silent"] is False


def test_zwave_plugin_uses_the_sleeping_delay_for_battery_nodes() -> None:
    plugin = _silence_plugin(
        ZWaveNodeResult(
            node_id=5,
            status="asleep",
            can_sleep=True,
            last_seen="2026-11-07T08:00:00+01:00",
        ),
        config=ZWaveConfig(
            last_seen_alert_minutes=60,
            sleeping_last_seen_alert_minutes=1440,
        ),
    )

    node = plugin.execute(url="ws://zwave:3000").metadata["nodes"][0]

    assert node["silence_threshold_minutes"] == 1440
    assert node["silent"] is False


def test_zwave_plugin_does_not_judge_unmonitored_or_undated_nodes() -> None:
    plugin = _silence_plugin(
        ZWaveNodeResult(node_id=6, status="alive", last_seen=None),
        ZWaveNodeResult(
            node_id=7,
            status="asleep",
            can_sleep=True,
            last_seen="2020-01-01T00:00:00+00:00",
        ),
        config=ZWaveConfig(last_seen_alert_minutes=60),
    )

    undated, unmonitored = plugin.execute(url="ws://zwave:3000").metadata["nodes"]

    assert undated["silent"] is None
    assert unmonitored["silent"] is None
