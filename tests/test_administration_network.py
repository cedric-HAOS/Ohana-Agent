"""Tests for Agent host network administration."""

from __future__ import annotations

import json
import subprocess
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path

import pytest
from pydantic import ValidationError

from administration import network_helper
from administration.models import AgentNetworkSettings
from administration.network import NetworkManagerRepository


def network_state() -> dict[str, object]:
    return {
        "schema_version": 1,
        "available": True,
        "interface": "eth0",
        "connection_name": "Wired connection 1",
        "method": "manual",
        "address": "192.168.1.10/24",
        "gateway": "192.168.1.1",
        "dns_servers": ["192.168.1.11", "192.168.1.12"],
        "active": True,
        "state": "100 (connected)",
        "pending_change": None,
    }


def test_network_settings_require_gateway_in_subnet() -> None:
    with pytest.raises(ValidationError):
        AgentNetworkSettings(
            interface="eth0",
            method="manual",
            address="192.168.1.10/24",
            gateway="192.168.2.1",
            dns_servers=["192.168.1.11"],
        )


def test_network_settings_accept_static_configuration() -> None:
    settings = AgentNetworkSettings(
        interface="eth0",
        method="manual",
        address="192.168.1.10/24",
        gateway="192.168.1.1",
        dns_servers=["192.168.1.11", "192.168.1.12"],
    )

    assert settings.address == IPv4Interface("192.168.1.10/24")
    assert settings.gateway == IPv4Address("192.168.1.1")


def test_network_repository_reads_helper_json() -> None:
    calls: list[list[str]] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(network_state()),
            stderr="",
        )

    repository = NetworkManagerRepository(
        helper_path=Path("/helper"),
        sudo_path=Path("/sudo"),
        runner=runner,
    )

    state = repository.read()

    assert state.address == IPv4Interface("192.168.1.10/24")
    assert calls == [["/sudo", "-n", "/helper", "status"]]


def test_network_repository_applies_with_rollback_delay() -> None:
    calls: list[tuple[list[str], str | None]] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        input_data = kwargs.get("input")
        calls.append((command, input_data if isinstance(input_data, str) else None))
        response = {
            "schema_version": 1,
            "transaction_id": "a" * 32,
            "expires_at": "2026-07-30T12:00:00Z",
            "state": network_state(),
        }
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(response),
            stderr="",
        )

    repository = NetworkManagerRepository(
        helper_path=Path("/helper"),
        sudo_path=Path("/sudo"),
        runner=runner,
    )
    change = repository.apply(
        {
            "schema_version": 1,
            "rollback_seconds": 120,
            "settings": {
                "interface": "eth0",
                "method": "manual",
                "address": "192.168.1.10/24",
                "gateway": "192.168.1.1",
                "dns_servers": ["192.168.1.11"],
            },
        }
    )

    assert change.transaction_id == "a" * 32
    assert calls[0][0] == [
        "/sudo",
        "-n",
        "/helper",
        "apply",
        "--rollback-seconds",
        "120",
    ]
    assert json.loads(calls[0][1] or "{}") == {
        "interface": "eth0",
        "method": "manual",
        "address": "192.168.1.10/24",
        "gateway": "192.168.1.1",
        "dns_servers": ["192.168.1.11"],
    }


def test_network_helper_rejects_a_second_pending_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        network_helper,
        "_pending_change",
        lambda: {"transaction_id": "a" * 32},
    )

    with pytest.raises(
        network_helper.NetworkHelperError,
        match="already pending",
    ):
        network_helper._apply(90)


def test_network_helper_rejects_unsafe_rollback_delay() -> None:
    with pytest.raises(
        network_helper.NetworkHelperError,
        match="between 30 and 300",
    ):
        network_helper._apply(10)


def test_network_helper_rejects_symbolic_state_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    state_directory = tmp_path / "network"
    try:
        state_directory.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symbolic links are unavailable: {error}")
    monkeypatch.setattr(network_helper, "STATE_DIRECTORY", state_directory)

    with pytest.raises(
        network_helper.NetworkHelperError,
        match="symbolic link",
    ):
        network_helper._pending_change()
