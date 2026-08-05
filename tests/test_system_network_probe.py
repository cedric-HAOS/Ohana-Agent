"""Tests for the operating-system network presence probe."""

import subprocess
from collections.abc import Sequence
from typing import Any

from plugins.network.system_network_probe import SystemNetworkProbe


class FakeRunner:
    def __init__(
        self,
        results: list[subprocess.CompletedProcess[str] | Exception],
    ) -> None:
        self.results = iter(results)
        self.commands: list[Sequence[str]] = []

    def __call__(self, command: Sequence[str], **kwargs: Any) -> Any:
        del kwargs
        self.commands.append(command)
        result = next(self.results)

        if isinstance(result, Exception):
            raise result

        return result


def completed(
    command: list[str],
    returncode: int,
    *,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_system_network_probe_uses_icmp_success() -> None:
    runner = FakeRunner([completed(["ping"], 0)])
    probe = SystemNetworkProbe(runner=runner, system_name="Linux")

    result = probe.probe("192.168.1.10", timeout=1.0)

    assert result.reachable is True
    assert result.method == "icmp"
    assert runner.commands == [["ping", "-c", "1", "-W", "1", "192.168.1.10"]]


def test_system_network_probe_accepts_windows_echo_reply() -> None:
    runner = FakeRunner(
        [
            completed(
                ["ping"],
                0,
                stdout="Reply from 192.168.1.10: bytes=32 time=2ms TTL=64",
            )
        ]
    )
    probe = SystemNetworkProbe(runner=runner, system_name="Windows")

    result = probe.probe("192.168.1.10", timeout=1.0)

    assert result.reachable is True
    assert result.method == "icmp"


def test_system_network_probe_rejects_windows_destination_unreachable() -> None:
    runner = FakeRunner(
        [
            completed(
                ["ping"],
                0,
                stdout=(
                    "Réponse de 192.168.1.148 : "
                    "Impossible de joindre l’hôte de destination."
                ),
            ),
            completed(["arp"], 0, stdout="Aucune entrée ARP trouvée."),
        ]
    )
    probe = SystemNetworkProbe(runner=runner, system_name="Windows")

    result = probe.probe("192.168.1.99", timeout=1.0)

    assert result.reachable is False
    assert result.method == "icmp"
    assert "Impossible de joindre" in (result.error or "")
    assert runner.commands[1] == ["arp", "-a", "192.168.1.99"]


def test_system_network_probe_accepts_arp_confirmation() -> None:
    runner = FakeRunner(
        [
            completed(["ping"], 1, stderr="no response"),
            completed(
                ["ip", "neigh"],
                0,
                stdout=("192.168.1.10 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE"),
            ),
        ]
    )
    probe = SystemNetworkProbe(runner=runner, system_name="Linux")

    result = probe.probe("192.168.1.10", timeout=1.0)

    assert result.reachable is True
    assert result.method == "arp"
    assert runner.commands[1] == [
        "ip",
        "neigh",
        "show",
        "192.168.1.10",
    ]


def test_system_network_probe_returns_unknown_when_ping_is_unavailable() -> None:
    runner = FakeRunner([FileNotFoundError("ping")])
    probe = SystemNetworkProbe(runner=runner, system_name="Linux")

    result = probe.probe("192.168.1.10", timeout=1.0)

    assert result.reachable is None
    assert result.method is None
    assert "Unable to execute ICMP probe" in (result.error or "")


def test_system_network_probe_resolves_hostname_before_icmp() -> None:
    runner = FakeRunner([completed(["ping"], 0)])
    resolver_calls: list[tuple[str, object]] = []

    def resolver(host: str, port: object, **kwargs: object):
        resolver_calls.append((host, port))
        assert kwargs["type"]
        return [(2, 1, 6, "", ("192.168.1.71", 0))]

    probe = SystemNetworkProbe(
        runner=runner,
        resolver=resolver,
        system_name="Linux",
    )

    result = probe.probe("she-01.ohana.lan", timeout=1.0)

    assert resolver_calls == [("she-01.ohana.lan", None)]
    assert result.address == "she-01.ohana.lan"
    assert result.resolved_address == "192.168.1.71"
    assert result.reachable is True
    assert runner.commands == [["ping", "-c", "1", "-W", "1", "192.168.1.71"]]


def test_system_network_probe_reports_hostname_resolution_error() -> None:
    def resolver(host: str, port: object, **kwargs: object):
        del host, port, kwargs
        raise OSError("name not known")

    probe = SystemNetworkProbe(
        runner=FakeRunner([]),
        resolver=resolver,
        system_name="Linux",
    )

    result = probe.probe("missing.ohana.lan", timeout=1.0)

    assert result.reachable is None
    assert result.resolved_address is None
    assert "Unable to resolve hostname" in (result.error or "")
