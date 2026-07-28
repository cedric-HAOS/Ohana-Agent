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


def test_zwave_check_retries_until_driver_is_ready() -> None:
    client = FakeZWaveClient(
        [
            ZWaveHealthResult(
                url="ws://192.168.1.11:3000",
                healthy=False,
                error="not ready",
            ),
            ZWaveHealthResult(
                url="ws://192.168.1.11:3000",
                healthy=True,
                response="Z-Wave JS driver ready",
                server_version="3.2.0",
                driver_version="15.0.0",
                home_id="0x12345678",
                node_count=12,
            ),
        ]
    )

    result = ZWaveCheck(client=client).check(
        "ws://192.168.1.11:3000",
        timeout=1.5,
        retries=1,
        verify_tls=False,
    )

    assert result.healthy is True
    assert result.attempts == 2
    assert result.node_count == 12
    assert result.server_version == "3.2.0"
    assert client.calls == [
        ("ws://192.168.1.11:3000", 1.5, False),
        ("ws://192.168.1.11:3000", 1.5, False),
    ]
