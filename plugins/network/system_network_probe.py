"""Operating-system network presence probe."""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter

from plugins.network.network_probe_result import NetworkProbeResult

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(slots=True)
class SystemNetworkProbe:
    """Probe an address with ICMP and confirm local neighbors through ARP."""

    runner: CommandRunner = subprocess.run
    system_name: str | None = None

    def probe(self, address: str, *, timeout: float) -> NetworkProbeResult:
        """Return presence detected by ICMP or the local neighbor table."""
        resolved_system = (self.system_name or platform.system()).lower()
        ping_command = self._ping_command(
            address,
            timeout=timeout,
            system_name=resolved_system,
        )
        started_at = perf_counter()

        try:
            completed = self.runner(
                ping_command,
                capture_output=True,
                text=True,
                timeout=max(timeout + 1.0, 2.0),
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as error:
            return NetworkProbeResult(
                address=address,
                reachable=None,
                error=f"Unable to execute ICMP probe: {error}",
            )

        latency_ms = (perf_counter() - started_at) * 1000

        if completed.returncode == 0:
            return NetworkProbeResult(
                address=address,
                reachable=True,
                method="icmp",
                latency_ms=latency_ms,
            )

        arp_result = self._probe_neighbor_table(
            address,
            system_name=resolved_system,
            timeout=timeout,
        )

        if arp_result is True:
            return NetworkProbeResult(
                address=address,
                reachable=True,
                method="arp",
                latency_ms=latency_ms,
            )

        return NetworkProbeResult(
            address=address,
            reachable=False,
            method="icmp",
            latency_ms=latency_ms,
            error=self._command_error(completed),
        )

    def _probe_neighbor_table(
        self,
        address: str,
        *,
        system_name: str,
        timeout: float,
    ) -> bool | None:
        command = self._neighbor_command(address, system_name=system_name)

        if command is None:
            return None

        try:
            completed = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=max(timeout, 1.0),
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return None

        output = f"{completed.stdout}\n{completed.stderr}".lower()

        if completed.returncode != 0 or address.lower() not in output:
            return False

        unavailable_states = ("failed", "incomplete", "no arp entries")
        return not any(state in output for state in unavailable_states)

    @staticmethod
    def _ping_command(
        address: str,
        *,
        timeout: float,
        system_name: str,
    ) -> Sequence[str]:
        if system_name == "windows":
            return [
                "ping",
                "-n",
                "1",
                "-w",
                str(max(1, round(timeout * 1000))),
                address,
            ]

        return [
            "ping",
            "-c",
            "1",
            "-W",
            str(max(1, round(timeout))),
            address,
        ]

    @staticmethod
    def _neighbor_command(
        address: str,
        *,
        system_name: str,
    ) -> Sequence[str] | None:
        if system_name == "windows":
            return ["arp", "-a", address]

        if system_name in {"linux", "freebsd"}:
            return ["ip", "neigh", "show", address]

        return None

    @staticmethod
    def _command_error(completed: subprocess.CompletedProcess[str]) -> str:
        detail = (completed.stderr or completed.stdout or "").strip()

        if detail:
            return detail

        return f"ICMP probe exited with status {completed.returncode}."
