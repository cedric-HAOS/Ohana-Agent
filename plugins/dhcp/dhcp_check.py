"""Local dnsmasq status and lease-pool observation."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from ipaddress import IPv4Address
from pathlib import Path
from time import time

from administration.dhcp import DnsmasqDHCPRepository
from administration.models import DHCPLease
from plugins.dhcp.dhcp_check_result import DHCPCheckResult

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class DHCPCheck:
    """Observe a local dnsmasq service without requesting a synthetic lease."""

    def __init__(
        self,
        *,
        command_runner: CommandRunner = subprocess.run,
        wall_clock: Callable[[], float] = time,
    ) -> None:
        self._command_runner = command_runner
        self._wall_clock = wall_clock

    def check(
        self,
        server: str,
        *,
        port: int,
        service_id: str,
        main_config_path: Path,
        leases_path: Path,
        service_status_command: Sequence[str] | None,
        timeout: float,
    ) -> DHCPCheckResult:
        """Read daemon state, configured pool and active dnsmasq leases."""
        normalized_server = server.strip()
        normalized_service_id = service_id.strip()

        if not normalized_server:
            raise ValueError("server must not be empty.")

        if not normalized_service_id:
            raise ValueError("service_id must not be empty.")

        if isinstance(port, bool) or not 1 <= port <= 65_535:
            raise ValueError("port must be between 1 and 65535.")

        if timeout <= 0:
            raise ValueError("timeout must be greater than zero.")

        service_active, status_output, status_error = self._read_service_status(
            service_status_command,
            timeout=timeout,
        )

        try:
            if not main_config_path.is_file():
                raise OSError(f"DHCP configuration file not found: {main_config_path}")

            repository = DnsmasqDHCPRepository(
                main_config_path=main_config_path,
                reservation_paths={},
                leases_path=leases_path,
            )
            settings = repository.read_settings()
            range_start = settings.range_start
            range_end = settings.range_end
            lease_count, expired_lease_count = self._count_active_leases(
                repository.read_leases(),
                range_start=range_start,
                range_end=range_end,
            )
        except (OSError, ValueError) as error:
            return DHCPCheckResult(
                server=normalized_server,
                port=port,
                service_id=normalized_service_id,
                healthy=False,
                service_active=service_active,
                status_output=status_output,
                error=str(error),
            )

        pool_size = int(range_end) - int(range_start) + 1
        pool_usage_percent = lease_count / pool_size * 100
        error = status_error

        return DHCPCheckResult(
            server=normalized_server,
            port=port,
            service_id=normalized_service_id,
            healthy=error is None,
            service_active=service_active,
            range_start=str(range_start),
            range_end=str(range_end),
            pool_size=pool_size,
            lease_count=lease_count,
            available_address_count=pool_size - lease_count,
            expired_lease_count=expired_lease_count,
            pool_usage_percent=pool_usage_percent,
            status_output=status_output,
            error=error,
        )

    def _read_service_status(
        self,
        command: Sequence[str] | None,
        *,
        timeout: float,
    ) -> tuple[bool | None, str | None, str | None]:
        if command is None:
            return None, None, None

        normalized_command = tuple(part.strip() for part in command if part.strip())

        if not normalized_command:
            return None, None, "DHCP service status command must not be empty."

        try:
            completed = self._command_runner(
                normalized_command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, None, f"Unable to query DHCP service status: {error}"

        output = (completed.stdout or completed.stderr or "").strip() or None

        if completed.returncode != 0:
            detail = output or f"exit status {completed.returncode}"
            return False, output, f"DHCP service is not active: {detail}"

        return True, output, None

    def _count_active_leases(
        self,
        leases: list[DHCPLease],
        *,
        range_start: IPv4Address,
        range_end: IPv4Address,
    ) -> tuple[int, int]:
        now = int(self._wall_clock())
        active_addresses: set[IPv4Address] = set()
        expired_lease_count = 0

        for lease in leases:
            address = IPv4Address(lease.address)

            if not int(range_start) <= int(address) <= int(range_end):
                continue

            if lease.expires_at != 0 and lease.expires_at <= now:
                expired_lease_count += 1
                continue

            active_addresses.add(address)

        return len(active_addresses), expired_lease_count
