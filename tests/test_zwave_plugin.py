"""Tests for the Z-Wave observation plugin."""

import pytest

from plugins.zwave.zwave_config import ZWaveConfig
from plugins.zwave.zwave_plugin import ZWavePlugin
from plugins.zwave.zwave_result import ZWaveHealthResult


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
            url="http://192.168.1.54:8091/health/zwave",
            healthy=True,
            status_code=200,
            response="OK",
        )
    )
    plugin = ZWavePlugin(
        check=check,
        config=ZWaveConfig(timeout=2.0, retries=2, verify_tls=False),
    )

    result = plugin.execute(
        url="http://192.168.1.54:8091/health/zwave",
    )

    assert result.success is True
    assert result.check == "zwave.status"
    assert result.metadata["status_code"] == 200
    assert check.calls == [("http://192.168.1.54:8091/health/zwave", 2.0, 2, False)]


def test_zwave_plugin_requires_health_url() -> None:
    with pytest.raises(ValueError, match="url"):
        ZWavePlugin().execute(url="")
