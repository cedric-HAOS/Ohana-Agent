"""Tests for Z-Wave health retry behavior."""

from plugins.zwave.zwave_check import ZWaveCheck
from plugins.zwave.zwave_result import ZWaveHealthResult


class FakeZWaveClient:
    def __init__(self, results: list[ZWaveHealthResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, float, bool]] = []

    def query(
        self,
        url: str,
        *,
        timeout: float,
        verify_tls: bool,
    ) -> ZWaveHealthResult:
        self.calls.append((url, timeout, verify_tls))
        return self.results[len(self.calls) - 1]


def test_zwave_check_retries_until_controller_is_connected() -> None:
    client = FakeZWaveClient(
        [
            ZWaveHealthResult(
                url="http://zwave/health/zwave",
                healthy=False,
                status_code=500,
                error="not connected",
            ),
            ZWaveHealthResult(
                url="http://zwave/health/zwave",
                healthy=True,
                status_code=200,
                response="OK",
            ),
        ]
    )

    result = ZWaveCheck(client=client).check(
        "http://zwave/health/zwave",
        timeout=1.5,
        retries=1,
        verify_tls=False,
    )

    assert result.healthy is True
    assert result.attempts == 2
    assert result.status_code == 200
    assert client.calls == [
        ("http://zwave/health/zwave", 1.5, False),
        ("http://zwave/health/zwave", 1.5, False),
    ]
