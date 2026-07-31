"""dnsmasq-backed DHCP configuration administration."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Mapping
from ipaddress import IPv4Address
from pathlib import Path
from tempfile import NamedTemporaryFile

from administration.models import (
    DHCPAdministrationState,
    DHCPConfiguration,
    DHCPLease,
    DHCPReservation,
    DHCPReservationCategory,
    DHCPSettings,
)

DEFAULT_SETTINGS = DHCPSettings(
    interface="eth0",
    range_start="192.168.1.100",
    range_end="192.168.1.199",
    subnet_mask="255.255.255.0",
    lease_duration="24h",
    gateway="192.168.1.1",
    dns_servers=["192.168.1.11", "192.168.1.12"],
    ntp_servers=["192.168.1.10"],
    domain="ohana.lan",
)

CATEGORY_LABELS: dict[DHCPReservationCategory, str] = {
    "infrastructure": "Infrastructure",
    "servers": "Serveurs",
    "network": "Infrastructure réseau",
    "home_automation": "Passerelles domotiques",
    "critical": "Équipements critiques",
}


class DHCPConfigurationError(ValueError):
    """Raised when the installed dnsmasq configuration is unsupported."""


class DnsmasqDHCPRepository:
    """Read and atomically update Ohana's dnsmasq configuration files."""

    def __init__(
        self,
        *,
        main_config_path: Path,
        reservation_paths: Mapping[DHCPReservationCategory, Path],
        leases_path: Path,
        server_node_id: str = "infra-01",
        validation_command: tuple[str, ...] | None = None,
        reload_request_path: Path | None = None,
    ) -> None:
        self.main_config_path = main_config_path
        self.reservation_paths = dict(reservation_paths)
        self.leases_path = leases_path
        self.server_node_id = server_node_id
        self.validation_command = validation_command
        self.reload_request_path = reload_request_path

    def read(self) -> DHCPAdministrationState:
        """Return editable configuration and current leases."""
        configuration = self.read_configuration()

        return DHCPAdministrationState(
            **configuration.model_dump(),
            leases=self.read_leases(),
        )

    def read_configuration(self) -> DHCPConfiguration:
        """Read the supported dnsmasq directives."""
        settings = self.read_settings()
        reservations: list[DHCPReservation] = []

        for category, path in self.reservation_paths.items():
            reservations.extend(
                self._read_reservations(
                    path,
                    category,
                )
            )

        return DHCPConfiguration(
            server_node_id=self.server_node_id,
            settings=settings,
            reservations=reservations,
        )

    def write(self, configuration: DHCPConfiguration) -> DHCPAdministrationState:
        """Validate and persist a complete DHCP configuration."""
        stale_lease_macs = self._stale_lease_macs(configuration)
        rendered_files = {
            self.main_config_path: self._render_main(configuration.settings),
        }

        for category, path in self.reservation_paths.items():
            rendered_files[path] = self._render_reservations(
                category,
                [
                    reservation
                    for reservation in configuration.reservations
                    if reservation.category == category
                ],
            )

        previous_contents = {
            path: (path.read_bytes() if path.is_file() else None)
            for path in rendered_files
        }

        try:
            for path, content in rendered_files.items():
                self._atomic_write(
                    path,
                    content,
                )

            self._validate_dnsmasq()
            self._request_reload(stale_lease_macs)
        except (OSError, DHCPConfigurationError):
            self._restore(
                previous_contents,
            )
            raise

        return self.read()

    def read_leases(self) -> list[DHCPLease]:
        """Parse dnsmasq's lease database when it is available."""
        if not self.leases_path.is_file():
            return []

        leases: list[DHCPLease] = []

        for line_number, raw_line in enumerate(
            self.leases_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            line = raw_line.strip()

            if not line:
                continue

            parts = line.split()

            if len(parts) < 5:
                raise DHCPConfigurationError(
                    f"Invalid dnsmasq lease at line {line_number}"
                )

            expires_at, mac_address, address, hostname, client_id = parts[:5]
            leases.append(
                DHCPLease(
                    expires_at=int(expires_at),
                    mac_address=mac_address,
                    address=address,
                    hostname=None if hostname == "*" else hostname,
                    client_id=None if client_id == "*" else client_id,
                )
            )

        return leases

    def read_settings(self) -> DHCPSettings:
        """Read the supported dnsmasq settings without reservations."""
        if not self.main_config_path.is_file():
            return DEFAULT_SETTINGS.model_copy(deep=True)

        directives = self._read_directives(self.main_config_path)
        range_values = self._required_values(
            directives,
            "dhcp-range",
            expected=4,
        )

        gateway = self._option_values(
            directives,
            "router",
        )
        dns_servers = self._option_values(
            directives,
            "dns-server",
        )
        ntp_servers = self._option_values(
            directives,
            "ntp-server",
        )

        return DHCPSettings(
            interface=self._required_single(directives, "interface"),
            range_start=range_values[0],
            range_end=range_values[1],
            subnet_mask=range_values[2],
            lease_duration=range_values[3],
            gateway=gateway[0],
            dns_servers=dns_servers,
            ntp_servers=ntp_servers,
            domain=self._required_single(directives, "domain"),
        )

    @staticmethod
    def _read_directives(path: Path) -> dict[str, list[str]]:
        directives: dict[str, list[str]] = {}

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", maxsplit=1)
            directives.setdefault(key.strip(), []).append(value.strip())

        return directives

    @staticmethod
    def _required_single(
        directives: Mapping[str, list[str]],
        key: str,
    ) -> str:
        values = directives.get(key, [])

        if len(values) != 1:
            raise DHCPConfigurationError(
                f"dnsmasq directive {key!r} must be declared exactly once"
            )

        return values[0]

    @classmethod
    def _required_values(
        cls,
        directives: Mapping[str, list[str]],
        key: str,
        *,
        expected: int,
    ) -> list[str]:
        values = [
            part.strip()
            for part in cls._required_single(
                directives,
                key,
            ).split(",")
        ]

        if len(values) != expected:
            raise DHCPConfigurationError(
                f"dnsmasq directive {key!r} must contain {expected} values"
            )

        return values

    @staticmethod
    def _option_values(
        directives: Mapping[str, list[str]],
        option_name: str,
    ) -> list[IPv4Address]:
        prefix = f"option:{option_name},"

        for directive in directives.get("dhcp-option", []):
            if directive.startswith(prefix):
                return [
                    IPv4Address(value.strip())
                    for value in directive.removeprefix(prefix).split(",")
                ]

        raise DHCPConfigurationError(f"dnsmasq DHCP option {option_name!r} is missing")

    @staticmethod
    def _read_reservations(
        path: Path,
        category: DHCPReservationCategory,
    ) -> list[DHCPReservation]:
        if not path.is_file():
            return []

        reservations: list[DHCPReservation] = []

        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if not line.startswith("dhcp-host="):
                raise DHCPConfigurationError(
                    f"Unsupported directive in {path} at line {line_number}"
                )

            values = [
                value.strip() for value in line.removeprefix("dhcp-host=").split(",")
            ]

            if len(values) != 3:
                raise DHCPConfigurationError(
                    f"Invalid reservation in {path} at line {line_number}"
                )

            reservations.append(
                DHCPReservation(
                    mac_address=values[0],
                    address=values[1],
                    hostname=values[2],
                    category=category,
                )
            )

        return reservations

    @staticmethod
    def _render_main(settings: DHCPSettings) -> str:
        dns_servers = ",".join(str(server) for server in settings.dns_servers)
        ntp_servers = ",".join(str(server) for server in settings.ntp_servers)

        return "\n".join(
            [
                "#################################################",
                "# Ohana-House",
                "# Configuration DHCP gérée par Ohana-Agent",
                "#################################################",
                "",
                f"interface={settings.interface}",
                "bind-interfaces",
                "",
                "domain-needed",
                "bogus-priv",
                "",
                "dhcp-authoritative",
                "",
                (
                    "dhcp-range="
                    f"{settings.range_start},{settings.range_end},"
                    f"{settings.subnet_mask},{settings.lease_duration}"
                ),
                "",
                f"dhcp-option=option:router,{settings.gateway}",
                f"dhcp-option=option:dns-server,{dns_servers}",
                f"dhcp-option=option:ntp-server,{ntp_servers}",
                "",
                f"domain={settings.domain}",
                f"local=/{settings.domain}/",
                "expand-hosts",
                "",
            ]
        )

    @staticmethod
    def _render_reservations(
        category: DHCPReservationCategory,
        reservations: list[DHCPReservation],
    ) -> str:
        lines = [
            "#################################################",
            f"# {CATEGORY_LABELS[category]}",
            "# Réservations gérées par Ohana-Agent",
            "#################################################",
            "",
        ]
        lines.extend(
            (
                f"dhcp-host={reservation.mac_address},"
                f"{reservation.address},{reservation.hostname}"
            )
            for reservation in sorted(
                reservations,
                key=lambda item: int(item.address),
            )
        )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _atomic_write(
        path: Path,
        content: str,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path: Path | None = None

        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)

            os.replace(
                temporary_path,
                path,
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _validate_dnsmasq(self) -> None:
        if self.validation_command is None:
            return

        try:
            result = subprocess.run(
                self.validation_command,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (
            OSError,
            subprocess.TimeoutExpired,
        ) as error:
            raise DHCPConfigurationError(
                f"Unable to validate dnsmasq configuration: {error}"
            ) from error

        if result.returncode == 0:
            return

        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"exit code {result.returncode}"
        )
        raise DHCPConfigurationError(f"dnsmasq rejected the configuration: {detail}")

    def _stale_lease_macs(
        self,
        configuration: DHCPConfiguration,
    ) -> list[str]:
        reserved_addresses = {
            reservation.mac_address: reservation.address
            for reservation in configuration.reservations
        }
        reserved_macs = {
            reservation.address: reservation.mac_address
            for reservation in configuration.reservations
        }

        return sorted(
            {
                lease.mac_address
                for lease in self.read_leases()
                if (
                    lease.mac_address in reserved_addresses
                    and lease.address != reserved_addresses[lease.mac_address]
                )
                or (
                    lease.address in reserved_macs
                    and lease.mac_address != reserved_macs[lease.address]
                )
            }
        )

    def _request_reload(self, stale_lease_macs: list[str]) -> None:
        if self.reload_request_path is None:
            return

        self._atomic_write(
            self.reload_request_path,
            json.dumps(
                {
                    "schema_version": 1,
                    "requested_at_ns": time.time_ns(),
                    "stale_lease_macs": stale_lease_macs,
                },
                separators=(",", ":"),
            )
            + "\n",
        )

    def _restore(
        self,
        previous_contents: Mapping[Path, bytes | None],
    ) -> None:
        for path, content in previous_contents.items():
            if content is None:
                path.unlink(missing_ok=True)
                continue

            self._atomic_write(
                path,
                content.decode("utf-8"),
            )
