"""Read-only package update state of the Agent host."""

import gzip
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ohana_agent.host.system_updates import (
    SystemUpdateRequester,
    parse_simulated_upgrade,
    read_system_updates,
)

SIMULATION = """\
NOTE: This is only a simulation!
Reading package lists...
The following packages have been kept back:
  linux-image-rpi-v8 raspi-firmware
The following packages will be upgraded:
  libssl3t64 curl
Inst libssl3t64 [3.5.1-1] (3.5.1-1+deb13u1 Debian-Security:13/stable-security [arm64])
Inst curl [8.14.1-2] (8.14.1-2+deb13u2 Debian:13.1/stable [arm64])
Inst linux-image-6.12.48+rpt-rpi-v8 (6.12.48-1+rpt1 Raspberry Pi:trixie [arm64])
Conf libssl3t64 (3.5.1-1+deb13u1 Debian-Security:13/stable-security [arm64])
"""

NOW = 1_800_000_000.0


def _apt_get(tmp_path: Path) -> Path:
    path = tmp_path / "apt-get"
    path.write_text("", encoding="utf-8")
    return path


def _lists(tmp_path: Path, *, age_days: float) -> Path:
    directory = tmp_path / "lists"
    directory.mkdir()
    release = directory / "deb.debian.org_debian_dists_trixie_InRelease"
    release.write_text("", encoding="utf-8")
    stamp = NOW - age_days * 86400
    os.utime(release, (stamp, stamp))
    return directory


def _read(tmp_path: Path, *, age_days: float = 0.5, stdout: str = SIMULATION, **kwargs):
    return read_system_updates(
        apt_get_path=_apt_get(tmp_path),
        lists_directory=_lists(tmp_path, age_days=age_days),
        periodic_stamp=tmp_path / "missing-stamp",
        history_path=tmp_path / "history.log",
        reboot_path=tmp_path / "reboot-required",
        reboot_packages_path=tmp_path / "reboot-required.pkgs",
        runner=lambda *_a, **_k: SimpleNamespace(
            stdout=stdout, stderr="", returncode=0
        ),
        clock=lambda: NOW,
        **kwargs,
    )


def test_parse_separates_security_new_and_held_back_packages():
    parsed = parse_simulated_upgrade(SIMULATION)

    by_name = {package["name"]: package for package in parsed["pending"]}
    assert set(by_name) == {"libssl3t64", "curl", "linux-image-6.12.48+rpt-rpi-v8"}
    assert by_name["libssl3t64"]["security"] is True
    assert by_name["curl"]["security"] is False
    assert by_name["linux-image-6.12.48+rpt-rpi-v8"]["new_package"] is True
    assert parsed["held_back"] == ["linux-image-rpi-v8", "raspi-firmware"]


def test_security_updates_come_first_and_flag_the_kernel(tmp_path):
    state = _read(tmp_path)

    assert state["status"] == "security_updates"
    assert state["security_count"] == 1
    assert state["pending_count"] == 3
    assert state["packages"][0]["name"] == "libssl3t64"
    assert state["kernel_pending"] is True
    assert state["lists_stale"] is False


def test_stale_package_lists_hide_a_false_zero(tmp_path):
    state = _read(tmp_path, age_days=26, stdout="Reading package lists...\n")

    assert state["pending_count"] == 0
    assert state["lists_stale"] is True
    assert state["status"] == "stale_lists"
    assert state["lists_age_days"] == 26.0


def test_reboot_required_lists_the_packages(tmp_path):
    (tmp_path / "reboot-required").write_text("*** restart required\n")
    (tmp_path / "reboot-required.pkgs").write_text("linux-image-6.12\nlibc6\n")

    state = _read(tmp_path, stdout="Reading package lists...\n")

    assert state["status"] == "reboot_required"
    assert state["reboot_packages"] == ["libc6", "linux-image-6.12"]


def test_up_to_date_when_lists_are_fresh_and_nothing_is_pending(tmp_path):
    state = _read(tmp_path, stdout="Reading package lists...\n")

    assert state["status"] == "up_to_date"
    assert state["reboot_required"] is False


def test_last_apt_run_falls_back_to_the_rotated_log(tmp_path):
    history = (
        "Start-Date: 2026-10-09  16:58:47\n"
        "Commandline: apt-get install -y dnsutils\n"
        "Install: dnsutils:arm64 (9.20), bind9-dnsutils:arm64 (9.20)\n"
        "End-Date: 2026-10-09  16:58:50\n"
    )
    (tmp_path / "history.log").write_text("", encoding="utf-8")
    with gzip.open(tmp_path / "history.log.1.gz", "wt", encoding="utf-8") as target:
        target.write(history)

    state = _read(tmp_path, stdout="Reading package lists...\n")

    assert state["last_apt_run"]["command"] == "apt-get install -y dnsutils"
    assert state["last_apt_run"]["changes"] == {"Install": 2}


def test_failed_simulation_raises_with_the_cause(tmp_path):
    with pytest.raises(RuntimeError, match="a échoué"):
        read_system_updates(
            apt_get_path=_apt_get(tmp_path),
            lists_directory=_lists(tmp_path, age_days=1),
            runner=lambda *_a, **_k: SimpleNamespace(
                stdout="", stderr="E: broken", returncode=100
            ),
            clock=lambda: NOW,
        )


def test_missing_apt_get_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_system_updates(apt_get_path=tmp_path / "absent")


def _service(tmp_path: Path, reader):
    from ohana_agent.api.service import AdministrationService
    from ohana_agent.infrastructure.repository import (
        InfrastructureConfigurationRepository,
    )

    return AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infrastructure.yaml"
        ),
        system_updates_reader=reader,
    )


def test_service_serves_the_state_and_caches_the_simulation(tmp_path):
    calls = []

    def reader():
        calls.append(1)
        return {"status": "up_to_date"}

    service = _service(tmp_path, reader)

    assert "system.updates.read" in service.capabilities().operations
    assert service.read_system_updates() == {"status": "up_to_date"}
    assert service.read_system_updates() == {"status": "up_to_date"}
    assert len(calls) == 1


def test_service_reports_an_unavailable_reader(tmp_path):
    service = _service(tmp_path, None)

    assert "system.updates.read" not in service.capabilities().operations
    with pytest.raises(LookupError):
        service.read_system_updates()


BOOT = 5_000.0  # monotonic seconds at the time of the test


def _requester(tmp_path: Path, shows: dict[str, dict[str, str]], *, installed=True):
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    if installed:
        for stem in ("system-refresh", "system-upgrade"):
            (systemd / f"ohana-{stem}.path").write_text("", encoding="utf-8")
    systemctl = tmp_path / "systemctl"
    systemctl.write_text("", encoding="utf-8")

    def runner(command, **_kwargs):
        values = shows.get(command[2], {})
        return SimpleNamespace(
            stdout="\n".join(f"{key}={value}" for key, value in values.items()),
            returncode=0,
        )

    return SystemUpdateRequester(
        request_directory=tmp_path / "run",
        systemd_directory=systemd,
        systemctl_path=systemctl,
        runner=runner,
        clock=lambda: NOW,
        monotonic=lambda: BOOT,
    )


SUCCEEDED = {
    "ActiveState": "inactive",
    "Result": "success",
    "ExecMainStatus": "0",
    "ExecMainStartTimestampMonotonic": str(int((BOOT - 120) * 1_000_000)),
    "ExecMainExitTimestampMonotonic": str(int((BOOT - 60) * 1_000_000)),
}
NEVER = {
    "ActiveState": "inactive",
    "Result": "success",
    "ExecMainStartTimestampMonotonic": "0",
}
RUNNING = {
    "ActiveState": "activating",
    **{k: v for k, v in SUCCEEDED.items() if k != "ActiveState"},
}


def test_status_reports_never_running_succeeded_and_failed(tmp_path):
    failed = {**SUCCEEDED, "Result": "exit-code", "ExecMainStatus": "100"}
    requester = _requester(
        tmp_path,
        {
            "ohana-system-refresh.service": SUCCEEDED,
            "ohana-system-upgrade.service": failed,
        },
    )

    status = requester.status()

    assert status["refresh"]["state"] == "succeeded"
    assert status["refresh"]["finished_at"] is not None
    assert status["upgrade"]["state"] == "failed"
    assert status["upgrade"]["exit_status"] == "100"


def test_status_without_a_run_is_never_and_running_has_no_end(tmp_path):
    requester = _requester(
        tmp_path,
        {
            "ohana-system-refresh.service": NEVER,
            "ohana-system-upgrade.service": RUNNING,
        },
    )

    status = requester.status()

    assert status["refresh"]["state"] == "never"
    assert status["upgrade"]["state"] == "running"
    assert status["upgrade"]["finished_at"] is None


def test_uninstalled_helpers_are_reported_and_refused(tmp_path):
    requester = _requester(tmp_path, {}, installed=False)

    assert requester.status() == {"installed": False}
    with pytest.raises(RuntimeError, match="Ohana-Installer"):
        requester.request("refresh")


def test_request_writes_only_the_chosen_request_file(tmp_path):
    requester = _requester(
        tmp_path,
        {"ohana-system-refresh.service": NEVER, "ohana-system-upgrade.service": NEVER},
    )

    result = requester.request("refresh")

    assert result == {"started": True, "busy": False, "action": "refresh"}
    assert sorted(path.name for path in (tmp_path / "run").iterdir()) == [
        "system-refresh.request"
    ]


def test_request_is_refused_while_a_helper_runs_and_for_unknown_actions(tmp_path):
    requester = _requester(
        tmp_path,
        {
            "ohana-system-refresh.service": NEVER,
            "ohana-system-upgrade.service": RUNNING,
        },
    )

    assert requester.request("refresh") == {
        "started": False,
        "busy": True,
        "action": "refresh",
    }
    assert not (tmp_path / "run").exists()
    with pytest.raises(ValueError):
        requester.request("dist-upgrade")


def test_service_refuses_an_upgrade_on_stale_lists_or_nothing_pending(tmp_path):
    from ohana_agent.api.service import AdministrationService
    from ohana_agent.infrastructure.repository import (
        InfrastructureConfigurationRepository,
    )

    requested = []

    class Requester:
        def status(self):
            return {"installed": True}

        def request(self, action):
            requested.append(action)
            return {"started": True, "busy": False, "action": action}

    state = {"lists_stale": True, "pending_count": 3}
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infrastructure.yaml"
        ),
        system_updates_reader=lambda: dict(state),
        system_update_requester=Requester(),
    )

    operations = service.capabilities().operations
    assert {"system.updates.refresh", "system.updates.apply"} <= set(operations)
    with pytest.raises(ValueError, match="périmées"):
        service.request_system_update("upgrade")
    state.update(lists_stale=False, pending_count=0)
    service._system_updates_cache = None  # the guard reuses a recent reading
    with pytest.raises(ValueError, match="Aucune mise à jour"):
        service.request_system_update("upgrade")
    state.update(pending_count=3)
    service._system_updates_cache = None  # the guard reuses a recent reading
    assert service.request_system_update("upgrade")["started"] is True
    # refreshing the lists needs no precondition
    state.update(lists_stale=True)
    service._system_updates_cache = None  # the guard reuses a recent reading
    assert service.request_system_update("refresh")["action"] == "refresh"
    assert requested == ["upgrade", "refresh"]
    assert service.read_system_updates()["helper"] == {"installed": True}


def test_service_keeps_the_last_list_while_apt_runs_then_rereads(tmp_path):
    from ohana_agent.api.service import AdministrationService
    from ohana_agent.infrastructure.repository import (
        InfrastructureConfigurationRepository,
    )

    reads = []
    helper = {
        "installed": True,
        "refresh": {"state": "never"},
        "upgrade": {"state": "never"},
    }

    class Requester:
        def status(self):
            return helper

        def request(self, action):
            helper["upgrade"] = {"state": "running"}
            return {"started": True, "busy": False, "action": action}

    def reader():
        reads.append(1)
        return {
            "lists_stale": False,
            "pending_count": len(reads) and 2 - len(reads) + 1,
        }

    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infrastructure.yaml"
        ),
        system_updates_reader=reader,
        system_update_requester=Requester(),
    )

    service.read_system_updates()
    service.request_system_update("upgrade")
    during = service.read_system_updates()
    assert len(reads) == 1  # the guard reuses the reading; none while running
    assert during["helper"]["upgrade"]["state"] == "running"
    helper["upgrade"] = {"state": "succeeded"}
    service.read_system_updates()
    assert len(reads) == 2  # expired by the request, read again once apt is done
