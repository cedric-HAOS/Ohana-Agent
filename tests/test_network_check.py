"""Tests for the network presence check retry policy."""

from plugins.network.network_check import NetworkCheck
from plugins.network.network_probe_result import NetworkProbeResult


class FakeProbe:
    def __init__(self, results: list[NetworkProbeResult]) -> None:
        self.results = iter(results)
        self.calls: list[tuple[str, float]] = []

    def probe(self, address: str, *, timeout: float) -> NetworkProbeResult:
        self.calls.append((address, timeout))
        return next(self.results)


def test_network_check_retries_until_device_is_reachable() -> None:
    probe = FakeProbe(
        [
            NetworkProbeResult(address="192.168.1.10", reachable=False),
            NetworkProbeResult(
                address="192.168.1.10",
                reachable=True,
                method="arp",
                latency_ms=4.5,
            ),
        ]
    )

    result = NetworkCheck(probe=probe).check(
        "192.168.1.10",
        timeout=1.5,
        retries=2,
    )

    assert result.reachable is True
    assert result.method == "arp"
    assert result.attempts == 2
    assert probe.calls == [
        ("192.168.1.10", 1.5),
        ("192.168.1.10", 1.5),
    ]


def test_network_check_stops_when_presence_is_unknown() -> None:
    probe = FakeProbe(
        [
            NetworkProbeResult(
                address="192.168.1.10",
                reachable=None,
                error="ping command unavailable",
            )
        ]
    )

    result = NetworkCheck(probe=probe).check(
        "192.168.1.10",
        retries=3,
    )

    assert result.reachable is None
    assert result.attempts == 1
