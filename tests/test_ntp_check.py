"""Tests for NTP retry behavior."""

from plugins.ntp.ntp_check import NTPCheck
from plugins.ntp.ntp_result import NTPResult


class FakeNTPClient:
    def __init__(self, results: list[NTPResult]) -> None:
        self.results = results
        self.calls = 0

    def query(
        self,
        server: str,
        *,
        port: int,
        timeout: float,
    ) -> NTPResult:
        del server, port, timeout
        result = self.results[self.calls]
        self.calls += 1
        return result


def test_ntp_check_retries_until_success() -> None:
    client = FakeNTPClient(
        [
            NTPResult(
                server="192.168.1.10",
                port=123,
                success=False,
                error="timeout",
            ),
            NTPResult(
                server="192.168.1.10",
                port=123,
                success=True,
                offset_ms=2.5,
                round_trip_ms=10.0,
                stratum=3,
                version=4,
                leap_indicator=0,
            ),
        ]
    )

    result = NTPCheck(client=client).check(
        "192.168.1.10",
        retries=1,
    )

    assert result.healthy is True
    assert result.attempts == 2
    assert result.offset_ms == 2.5
    assert client.calls == 2
