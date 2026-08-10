"""Tests for the restricted dnsmasq reload helper."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from administration import dhcp_reload_helper


def test_production_entrypoint_does_not_import_pydantic() -> None:
    script = """
import builtins
original_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "pydantic" or name.startswith("pydantic."):
        raise AssertionError("the DHCP reload entry point imported Pydantic")
    return original_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import dhcp_reload_entrypoint
assert callable(dhcp_reload_entrypoint.main)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def write_request(path: Path, stale_macs: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "requested_at_ns": 123,
                "stale_lease_macs": stale_macs,
            }
        ),
        encoding="utf-8",
    )


def successful_runner(
    calls: list[list[str]],
):
    def run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    return run


def test_reload_helper_removes_only_requested_stale_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = tmp_path / "dhcp-reload.request"
    leases_path = tmp_path / "dnsmasq.leases"
    write_request(request_path, ["B8:27:EB:33:4D:20"])
    leases_path.write_text(
        "1785573585 b8:27:eb:33:4d:20 192.168.1.14 linky-01 01:b8\n"
        "1785573585 2c:cf:67:4c:a5:f4 192.168.1.11 zwave-01 01:2c\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        dhcp_reload_helper.os,
        "chown",
        lambda *_args: None,
        raising=False,
    )
    calls: list[list[str]] = []

    result = dhcp_reload_helper.apply_reload(
        request_path=request_path,
        leases_path=leases_path,
        runner=successful_runner(calls),
    )

    assert result == {"schema_version": 1, "removed_leases": 1}
    assert "b8:27:eb:33:4d:20" not in leases_path.read_text(encoding="utf-8")
    assert "2c:cf:67:4c:a5:f4" in leases_path.read_text(encoding="utf-8")
    assert calls == [
        [str(dhcp_reload_helper.SYSTEMCTL), "stop", "dnsmasq.service"],
        [str(dhcp_reload_helper.SYSTEMCTL), "start", "dnsmasq.service"],
    ]


def test_reload_helper_restarts_dnsmasq_without_stale_lease(
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "dhcp-reload.request"
    leases_path = tmp_path / "dnsmasq.leases"
    write_request(request_path, [])
    original = "1785573585 aa:bb:cc:dd:ee:01 192.168.1.10 infra-01 01:aa\n"
    leases_path.write_text(original, encoding="utf-8")
    calls: list[list[str]] = []

    result = dhcp_reload_helper.apply_reload(
        request_path=request_path,
        leases_path=leases_path,
        runner=successful_runner(calls),
    )

    assert result["removed_leases"] == 0
    assert leases_path.read_text(encoding="utf-8") == original
    assert [command[1] for command in calls] == ["stop", "start"]


def test_reload_helper_rejects_invalid_mac_before_stopping_dnsmasq(
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "dhcp-reload.request"
    write_request(request_path, ["not-a-mac"])
    calls: list[list[str]] = []

    with pytest.raises(
        dhcp_reload_helper.DHCPReloadError,
        match="Invalid MAC",
    ):
        dhcp_reload_helper.apply_reload(
            request_path=request_path,
            leases_path=tmp_path / "dnsmasq.leases",
            runner=successful_runner(calls),
        )

    assert calls == []


def test_reload_helper_starts_dnsmasq_when_lease_purge_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = tmp_path / "dhcp-reload.request"
    write_request(request_path, ["AA:BB:CC:DD:EE:01"])
    calls: list[list[str]] = []
    monkeypatch.setattr(
        dhcp_reload_helper,
        "_purge_stale_leases",
        lambda *_args: (_ for _ in ()).throw(OSError("write failed")),
    )

    with pytest.raises(OSError, match="write failed"):
        dhcp_reload_helper.apply_reload(
            request_path=request_path,
            leases_path=tmp_path / "dnsmasq.leases",
            runner=successful_runner(calls),
        )

    assert [command[1] for command in calls] == ["stop", "start"]
