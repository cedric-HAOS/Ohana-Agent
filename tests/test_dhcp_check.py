import subprocess
from pathlib import Path

from plugins.dhcp.dhcp_check import DHCPCheck


def write_state(tmp_path: Path) -> tuple[Path, Path]:
    config_path = tmp_path / "dnsmasq.conf"
    leases_path = tmp_path / "dnsmasq.leases"
    config_path.write_text(
        """interface=eth0
dhcp-range=192.168.1.100,192.168.1.109,255.255.255.0,24h
dhcp-option=option:router,192.168.1.1
dhcp-option=option:dns-server,192.168.1.11,192.168.1.12
dhcp-option=option:ntp-server,192.168.1.10
domain=ohana.lan
""",
        encoding="utf-8",
    )
    leases_path.write_text(
        """2000 AA:BB:CC:DD:EE:01 192.168.1.101 host-1 *
900 AA:BB:CC:DD:EE:02 192.168.1.102 host-2 *
0 AA:BB:CC:DD:EE:03 192.168.1.103 host-3 *
2000 AA:BB:CC:DD:EE:04 192.168.1.20 reserved *
2000 AA:BB:CC:DD:EE:05 192.168.1.101 duplicate *
""",
        encoding="utf-8",
    )
    return config_path, leases_path


def test_dhcp_check_reads_service_and_active_pool(tmp_path: Path) -> None:
    config_path, leases_path = write_state(tmp_path)
    commands: list[tuple[str, ...]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert kwargs["timeout"] == 2.0
        return subprocess.CompletedProcess(command, 0, stdout="active\n", stderr="")

    result = DHCPCheck(
        command_runner=runner,
        wall_clock=lambda: 1000,
    ).check(
        "192.168.1.10",
        port=67,
        service_id="dhcp-primary",
        main_config_path=config_path,
        leases_path=leases_path,
        service_status_command=("systemctl", "is-active", "dnsmasq"),
        timeout=2.0,
    )

    assert commands == [("systemctl", "is-active", "dnsmasq")]
    assert result.healthy is True
    assert result.service_active is True
    assert result.status_output == "active"
    assert result.range_start == "192.168.1.100"
    assert result.range_end == "192.168.1.109"
    assert result.pool_size == 10
    assert result.lease_count == 2
    assert result.available_address_count == 8
    assert result.expired_lease_count == 1
    assert result.pool_usage_percent == 20.0
    assert result.error is None


def test_dhcp_check_accepts_missing_empty_leases_file(tmp_path: Path) -> None:
    config_path = tmp_path / "dnsmasq.conf"
    config_path.write_text(
        """interface=eth0
dhcp-range=192.168.1.100,192.168.1.199,255.255.255.0,24h
dhcp-option=option:router,192.168.1.1
dhcp-option=option:dns-server,192.168.1.11,192.168.1.12
dhcp-option=option:ntp-server,192.168.1.10
domain=ohana.lan
""",
        encoding="utf-8",
    )

    result = DHCPCheck(wall_clock=lambda: 1000).check(
        "192.168.1.10",
        port=67,
        service_id="dhcp-primary",
        main_config_path=config_path,
        leases_path=tmp_path / "missing.leases",
        service_status_command=None,
        timeout=1.0,
    )

    assert result.healthy is True
    assert result.service_active is None
    assert result.lease_count == 0
    assert result.available_address_count == 100
    assert result.pool_size == 100
    assert result.pool_usage_percent == 0.0


def test_dhcp_check_reports_inactive_service(tmp_path: Path) -> None:
    config_path, leases_path = write_state(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(command, 3, stdout="inactive\n", stderr="")

    result = DHCPCheck(
        command_runner=runner,
        wall_clock=lambda: 1000,
    ).check(
        "192.168.1.10",
        port=67,
        service_id="dhcp-primary",
        main_config_path=config_path,
        leases_path=leases_path,
        service_status_command=("systemctl", "is-active", "dnsmasq"),
        timeout=1.0,
    )

    assert result.healthy is False
    assert result.service_active is False
    assert result.status_output == "inactive"
    assert result.error == "DHCP service is not active: inactive"
    assert result.lease_count == 2


def test_dhcp_check_reports_invalid_pool(tmp_path: Path) -> None:
    config_path = tmp_path / "dnsmasq.conf"
    config_path.write_text("interface=eth0\n", encoding="utf-8")

    result = DHCPCheck().check(
        "192.168.1.10",
        port=67,
        service_id="dhcp-primary",
        main_config_path=config_path,
        leases_path=tmp_path / "leases",
        service_status_command=None,
        timeout=1.0,
    )

    assert result.healthy is False
    assert "'dhcp-range' must be declared exactly once" in (result.error or "")


def test_dhcp_check_reports_malformed_lease(tmp_path: Path) -> None:
    config_path = tmp_path / "dnsmasq.conf"
    leases_path = tmp_path / "dnsmasq.leases"
    config_path.write_text(
        """interface=eth0
dhcp-range=192.168.1.100,192.168.1.109,255.255.255.0,24h
dhcp-option=option:router,192.168.1.1
dhcp-option=option:dns-server,192.168.1.11,192.168.1.12
dhcp-option=option:ntp-server,192.168.1.10
domain=ohana.lan
""",
        encoding="utf-8",
    )
    leases_path.write_text("invalid lease\n", encoding="utf-8")

    result = DHCPCheck().check(
        "192.168.1.10",
        port=67,
        service_id="dhcp-primary",
        main_config_path=config_path,
        leases_path=leases_path,
        service_status_command=None,
        timeout=1.0,
    )

    assert result.healthy is False
    assert "Invalid dnsmasq lease" in (result.error or "")
