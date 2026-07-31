"""Tests for dnsmasq DHCP administration."""

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from administration import (
    DHCPConfiguration,
    DHCPConfigurationError,
    DHCPReservation,
    DHCPSettings,
    DnsmasqDHCPRepository,
)


def make_repository(
    temporary_path: Path,
) -> DnsmasqDHCPRepository:
    """Create a repository isolated in one temporary directory."""
    return DnsmasqDHCPRepository(
        main_config_path=temporary_path / "00-ohana.conf",
        reservation_paths={
            "infrastructure": (temporary_path / "10-infrastructure.conf"),
            "servers": temporary_path / "20-serveurs.conf",
            "network": (temporary_path / "30-infrastructure-reseau.conf"),
            "home_automation": (temporary_path / "40-passerelles-domotiques.conf"),
            "critical": (temporary_path / "50-equipements-critiques.conf"),
        },
        leases_path=temporary_path / "dnsmasq.leases",
    )


def make_configuration() -> DHCPConfiguration:
    """Return the documented Ohana-House DHCP configuration."""
    return DHCPConfiguration(
        server_node_id="infra-01",
        settings=DHCPSettings(
            interface="eth0",
            range_start="192.168.1.100",
            range_end="192.168.1.199",
            subnet_mask="255.255.255.0",
            lease_duration="24h",
            gateway="192.168.1.1",
            dns_servers=[
                "192.168.1.11",
                "192.168.1.12",
            ],
            ntp_servers=["192.168.1.10"],
            domain="ohana.lan",
        ),
        reservations=[
            DHCPReservation(
                mac_address="AA:BB:CC:DD:EE:01",
                address="192.168.1.10",
                hostname="infra-01",
                category="infrastructure",
            ),
            DHCPReservation(
                mac_address="AA:BB:CC:DD:EE:02",
                address="192.168.1.20",
                hostname="ha-01",
                category="servers",
            ),
        ],
    )


def test_dhcp_repository_round_trips_configuration(
    tmp_path: Path,
) -> None:
    repository = make_repository(tmp_path)

    saved = repository.write(make_configuration())

    assert saved.settings.range_start.exploded == "192.168.1.100"
    assert saved.settings.range_end.exploded == "192.168.1.199"
    assert [reservation.hostname for reservation in saved.reservations] == [
        "infra-01",
        "ha-01",
    ]
    assert "dhcp-option=option:dns-server,192.168.1.11,192.168.1.12" in (
        tmp_path / "00-ohana.conf"
    ).read_text(encoding="utf-8")


def test_dhcp_repository_reads_active_leases(
    tmp_path: Path,
) -> None:
    repository = make_repository(tmp_path)
    repository.write(make_configuration())
    (tmp_path / "dnsmasq.leases").write_text(
        "1784900000 aa:bb:cc:dd:ee:01 192.168.1.10 infra-01 01:aa\n",
        encoding="utf-8",
    )

    state = repository.read()

    assert len(state.leases) == 1
    assert state.leases[0].hostname == "infra-01"
    assert state.leases[0].mac_address == "AA:BB:CC:DD:EE:01"


def test_dhcp_repository_requests_purge_of_conflicting_reserved_lease(
    tmp_path: Path,
) -> None:
    repository = make_repository(tmp_path)
    repository.reload_request_path = tmp_path / "dhcp-reload.request"
    (tmp_path / "dnsmasq.leases").write_text(
        "1784900000 aa:bb:cc:dd:ee:01 192.168.1.14 infra-01 01:aa\n"
        "1784900000 aa:bb:cc:dd:ee:99 192.168.1.15 other 01:bb\n",
        encoding="utf-8",
    )

    repository.write(make_configuration())

    request = json.loads(repository.reload_request_path.read_text(encoding="utf-8"))
    assert request["schema_version"] == 1
    assert request["stale_lease_macs"] == ["AA:BB:CC:DD:EE:01"]


def test_dhcp_repository_preserves_lease_matching_its_reservation(
    tmp_path: Path,
) -> None:
    repository = make_repository(tmp_path)
    repository.reload_request_path = tmp_path / "dhcp-reload.request"
    (tmp_path / "dnsmasq.leases").write_text(
        "1784900000 aa:bb:cc:dd:ee:01 192.168.1.10 infra-01 01:aa\n",
        encoding="utf-8",
    )

    repository.write(make_configuration())

    request = json.loads(repository.reload_request_path.read_text(encoding="utf-8"))
    assert request["stale_lease_macs"] == []


def test_dhcp_repository_requests_purge_of_lease_occupying_reserved_address(
    tmp_path: Path,
) -> None:
    repository = make_repository(tmp_path)
    repository.reload_request_path = tmp_path / "dhcp-reload.request"
    (tmp_path / "dnsmasq.leases").write_text(
        "1784900000 aa:bb:cc:dd:ee:99 192.168.1.10 other 01:bb\n",
        encoding="utf-8",
    )

    repository.write(make_configuration())

    request = json.loads(repository.reload_request_path.read_text(encoding="utf-8"))
    assert request["stale_lease_macs"] == ["AA:BB:CC:DD:EE:99"]


def test_dhcp_configuration_rejects_duplicate_addresses() -> None:
    configuration = make_configuration()
    duplicate = configuration.reservations[0].model_copy(
        update={
            "mac_address": "AA:BB:CC:DD:EE:99",
            "hostname": "duplicate",
        }
    )

    with pytest.raises(
        ValidationError,
        match="duplicate address",
    ):
        DHCPConfiguration(
            settings=configuration.settings,
            server_node_id="infra-01",
            reservations=[
                *configuration.reservations,
                duplicate,
            ],
        )


def test_dhcp_settings_reject_range_outside_gateway_subnet() -> None:
    with pytest.raises(
        ValidationError,
        match="same subnet",
    ):
        DHCPSettings(
            interface="eth0",
            range_start="192.168.2.100",
            range_end="192.168.2.199",
            subnet_mask="255.255.255.0",
            lease_duration="24h",
            gateway="192.168.1.1",
            dns_servers=["192.168.1.11"],
            ntp_servers=["192.168.1.10"],
            domain="ohana.lan",
        )


def test_dhcp_repository_rolls_back_rejected_configuration(
    tmp_path: Path,
) -> None:
    repository = make_repository(tmp_path)
    repository.write(make_configuration())
    original_main = (tmp_path / "00-ohana.conf").read_text(encoding="utf-8")
    reload_request = tmp_path / "dhcp-reload.request"
    repository.validation_command = (
        sys.executable,
        "-c",
        "raise SystemExit(1)",
    )
    repository.reload_request_path = reload_request
    changed = make_configuration().model_copy(deep=True)
    changed.settings.range_end = "192.168.1.180"

    with pytest.raises(
        DHCPConfigurationError,
        match="dnsmasq rejected",
    ):
        repository.write(changed)

    assert (tmp_path / "00-ohana.conf").read_text(encoding="utf-8") == original_main
    assert not reload_request.exists()
