"""Tests for the NTP plugin observation contract."""

import pytest

from plugin.plugin_context import PluginContext
from plugin.plugin_runtime import PluginState
from plugins.ntp.ntp_check_result import NTPCheckResult
from plugins.ntp.ntp_config import NTPConfig, NTPPolicyConfig
from plugins.ntp.ntp_plugin import NTPPlugin


class FakeNTPCheck:
    def __init__(self, result: NTPCheckResult) -> None:
        self.result = result
        self.calls: list[tuple[str, int, float, int]] = []

    def check(
        self,
        server: str,
        *,
        port: int,
        timeout: float,
        retries: int,
    ) -> NTPCheckResult:
        self.calls.append((server, port, timeout, retries))
        return self.result


def make_context() -> PluginContext:
    return PluginContext(
        event_bus=object(),
        scheduler=None,
        dispatcher=None,
        memory=None,
        capability_manager=None,
        configuration=None,
        runtime=None,
    )


def test_ntp_plugin_returns_healthy_observer_result() -> None:
    check = FakeNTPCheck(
        NTPCheckResult(
            server="192.168.1.10",
            port=123,
            healthy=True,
            source_address="192.168.1.10",
            offset_ms=4.25,
            round_trip_ms=12.5,
            stratum=3,
            version=4,
            leap_indicator=0,
        )
    )
    plugin = NTPPlugin(
        check=check,
        config=NTPConfig(timeout=1.5, retries=2),
    )

    result = plugin.execute(server="192.168.1.10", port=123)

    assert result.success is True
    assert result.check == "ntp.query"
    assert result.latency == 12.5
    assert result.metadata["offset_ms"] == 4.25
    assert result.metadata["stratum"] == 3
    assert check.calls == [("192.168.1.10", 123, 1.5, 2)]


def test_ntp_plugin_marks_excessive_offset_unhealthy() -> None:
    plugin = NTPPlugin(
        check=FakeNTPCheck(
            NTPCheckResult(
                server="192.168.1.10",
                port=123,
                healthy=True,
                offset_ms=150.0,
                round_trip_ms=8.0,
                stratum=2,
            )
        ),
        config=NTPConfig(
            policy=NTPPolicyConfig(
                maximum_offset_ms=100.0,
                maximum_stratum=15,
            )
        ),
    )

    result = plugin.execute(server="192.168.1.10")

    assert result.success is False
    assert "offset exceeds" in result.message


def test_ntp_plugin_registers_and_validates_arguments() -> None:
    plugin = NTPPlugin()

    assert plugin.state is PluginState.LOADED

    plugin.register(make_context())

    assert plugin.state is PluginState.REGISTERED

    with pytest.raises(ValueError, match="server"):
        plugin.execute(server="")

    with pytest.raises(ValueError, match="port"):
        plugin.execute(server="192.168.1.10", port=0)
