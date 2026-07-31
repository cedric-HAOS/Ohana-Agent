"""Restricted root helper used to administer NetworkManager safely."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from administration.models import AgentNetworkSettings

NMCLI = Path("/usr/bin/nmcli")
SYSTEMCTL = Path("/usr/bin/systemctl")
SYSTEMD_RUN = Path("/usr/bin/systemd-run")
HELPER_PATH = Path("/usr/local/sbin/ohana-network-helper")
STATE_DIRECTORY = Path("/var/lib/ohana-agent/network")
TRANSACTION_PATTERN = re.compile(r"^[0-9a-f]{32}$")
INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,32}$")
MAXIMUM_INPUT_BYTES = 16 * 1024


class NetworkHelperError(RuntimeError):
    """Raised when a restricted NetworkManager operation cannot be completed."""


def _run(command: list[str], *, timeout: int = 20) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise NetworkHelperError(f"Unable to execute {command[0]}: {error}") from error

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise NetworkHelperError(detail or f"Command failed: {command[0]}")

    return result.stdout.strip()


def _nmcli(*arguments: str) -> str:
    if not NMCLI.is_file():
        raise NetworkHelperError("NetworkManager nmcli is unavailable")

    return _run([str(NMCLI), *arguments])


def _connection_property(connection: str, property_name: str) -> str:
    return _nmcli("--get-values", property_name, "connection", "show", connection)


def _device_property(interface: str, property_name: str) -> str:
    return _nmcli("--get-values", property_name, "device", "show", interface)


def _default_interface() -> str:
    output = _nmcli(
        "--terse",
        "--fields",
        "DEVICE,TYPE,STATE",
        "device",
        "status",
    )

    for line in output.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[1] == "ethernet" and parts[2] == "connected":
            return parts[0]

    raise NetworkHelperError("No connected Ethernet interface was found")


def _connection_for_interface(interface: str) -> str:
    connection = _device_property(interface, "GENERAL.CONNECTION").strip()

    if not connection or connection == "--":
        raise NetworkHelperError(
            f"No active NetworkManager connection exists for {interface}"
        )

    return connection


def _first_line(value: str) -> str | None:
    for line in value.splitlines():
        normalized = line.strip()
        if normalized and normalized != "--":
            return normalized
    return None


def _state(interface: str | None = None) -> dict[str, Any]:
    interface = interface or _default_interface()

    if INTERFACE_PATTERN.fullmatch(interface) is None:
        raise NetworkHelperError("Invalid network interface name")

    connection = _connection_for_interface(interface)
    method = _connection_property(connection, "ipv4.method").strip()
    address = _first_line(_device_property(interface, "IP4.ADDRESS"))
    gateway = _first_line(_device_property(interface, "IP4.GATEWAY"))
    dns = [
        line.strip()
        for line in _device_property(interface, "IP4.DNS").splitlines()
        if line.strip() and line.strip() != "--"
    ]
    raw_state = _device_property(interface, "GENERAL.STATE").strip()
    active = raw_state.startswith("100") or "connected" in raw_state.lower()

    return {
        "schema_version": 1,
        "available": True,
        "interface": interface,
        "connection_name": connection,
        "method": "auto" if method == "auto" else "manual",
        "address": address,
        "gateway": gateway,
        "dns_servers": dns,
        "active": active,
        "state": raw_state or "unknown",
        "pending_change": _pending_change(),
    }


def _snapshot(interface: str, connection: str) -> dict[str, Any]:
    return {
        "interface": interface,
        "connection_name": connection,
        "ipv4.method": _connection_property(connection, "ipv4.method").strip(),
        "ipv4.addresses": _connection_property(connection, "ipv4.addresses").strip(),
        "ipv4.gateway": _connection_property(connection, "ipv4.gateway").strip(),
        "ipv4.dns": _connection_property(connection, "ipv4.dns").strip(),
        "ipv4.ignore-auto-dns": _connection_property(
            connection,
            "ipv4.ignore-auto-dns",
        ).strip(),
    }


def _transaction_path(transaction_id: str) -> Path:
    if TRANSACTION_PATTERN.fullmatch(transaction_id) is None:
        raise NetworkHelperError("Invalid network transaction identifier")
    return STATE_DIRECTORY / f"{transaction_id}.json"


def _ensure_state_directory() -> None:
    """Create the root-only transaction directory without following a symlink."""
    STATE_DIRECTORY.parent.mkdir(parents=True, exist_ok=True)
    if STATE_DIRECTORY.is_symlink():
        raise NetworkHelperError("Network state directory cannot be a symbolic link")
    if STATE_DIRECTORY.exists() and not STATE_DIRECTORY.is_dir():
        raise NetworkHelperError("Network state path is not a directory")
    STATE_DIRECTORY.mkdir(mode=0o700, exist_ok=True)
    os.chmod(STATE_DIRECTORY, 0o700)


def _write_transaction(
    transaction_id: str,
    *,
    snapshot: dict[str, Any],
    requested: AgentNetworkSettings,
    rollback_seconds: int,
) -> Path:
    _ensure_state_directory()
    path = _transaction_path(transaction_id)
    payload = {
        "transaction_id": transaction_id,
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": (
            datetime.now(UTC) + timedelta(seconds=rollback_seconds)
        ).isoformat(),
        "snapshot": snapshot,
        "requested": requested.model_dump(mode="json"),
    }
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    path.chmod(0o600)
    return path


def _load_transaction(transaction_id: str) -> dict[str, Any]:
    path = _transaction_path(transaction_id)
    if not path.is_file() or path.is_symlink():
        raise NetworkHelperError("Network transaction was not found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NetworkHelperError("Network transaction is unreadable") from error
    if not isinstance(payload, dict):
        raise NetworkHelperError("Network transaction is invalid")
    return payload


def _pending_change() -> dict[str, Any] | None:
    if STATE_DIRECTORY.is_symlink():
        raise NetworkHelperError("Network state directory cannot be a symbolic link")
    if not STATE_DIRECTORY.is_dir():
        return None
    candidates = sorted(
        STATE_DIRECTORY.glob("*.json"), key=lambda path: path.stat().st_mtime
    )
    for path in reversed(candidates):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        return {
            "transaction_id": payload.get("transaction_id"),
            "expires_at": payload.get("expires_at"),
            "requested": payload.get("requested"),
        }
    return None


def _modify_connection(connection: str, settings: AgentNetworkSettings) -> None:
    command = [str(NMCLI), "connection", "modify", connection]
    if settings.method == "manual":
        command.extend(
            [
                "ipv4.method",
                "manual",
                "ipv4.addresses",
                str(settings.address),
                "ipv4.gateway",
                str(settings.gateway),
                "ipv4.dns",
                ",".join(str(server) for server in settings.dns_servers),
                "ipv4.ignore-auto-dns",
                "yes",
            ]
        )
    else:
        command.extend(
            [
                "ipv4.method",
                "auto",
                "ipv4.addresses",
                "",
                "ipv4.gateway",
                "",
                "ipv4.dns",
                "",
                "ipv4.ignore-auto-dns",
                "no",
            ]
        )
    _run(command)
    _nmcli("connection", "up", connection, "ifname", settings.interface)


def _restore_snapshot(snapshot: dict[str, Any]) -> None:
    connection = str(snapshot["connection_name"])
    interface = str(snapshot["interface"])
    command = [str(NMCLI), "connection", "modify", connection]
    for property_name in (
        "ipv4.method",
        "ipv4.addresses",
        "ipv4.gateway",
        "ipv4.dns",
        "ipv4.ignore-auto-dns",
    ):
        command.extend([property_name, str(snapshot.get(property_name, ""))])
    _run(command)
    _nmcli("connection", "up", connection, "ifname", interface)


def _schedule_rollback(transaction_id: str, rollback_seconds: int) -> None:
    if not SYSTEMD_RUN.is_file():
        raise NetworkHelperError("systemd-run is unavailable")
    unit = f"ohana-network-rollback-{transaction_id}"
    _run(
        [
            str(SYSTEMD_RUN),
            f"--unit={unit}",
            f"--on-active={rollback_seconds}s",
            "--collect",
            str(HELPER_PATH),
            "rollback",
            transaction_id,
        ]
    )


def _cancel_rollback(transaction_id: str) -> None:
    unit = f"ohana-network-rollback-{transaction_id}"
    if SYSTEMCTL.is_file():
        subprocess.run(
            [str(SYSTEMCTL), "stop", f"{unit}.timer", f"{unit}.service"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )


def _read_settings() -> AgentNetworkSettings:
    raw_payload = sys.stdin.read(MAXIMUM_INPUT_BYTES + 1)
    if len(raw_payload.encode("utf-8")) > MAXIMUM_INPUT_BYTES:
        raise NetworkHelperError("Network configuration is too large")
    try:
        payload = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NetworkHelperError(
            "A valid JSON network configuration is required"
        ) from error
    return AgentNetworkSettings.model_validate(payload)


def _apply(rollback_seconds: int) -> dict[str, Any]:
    if not 30 <= rollback_seconds <= 300:
        raise NetworkHelperError("Rollback delay must be between 30 and 300 seconds")
    if _pending_change() is not None:
        raise NetworkHelperError(
            "A network change is already pending confirmation or rollback"
        )
    settings = _read_settings()
    connection = _connection_for_interface(settings.interface)
    transaction_id = uuid.uuid4().hex
    _write_transaction(
        transaction_id,
        snapshot=_snapshot(settings.interface, connection),
        requested=settings,
        rollback_seconds=rollback_seconds,
    )
    try:
        _schedule_rollback(transaction_id, rollback_seconds)
        _modify_connection(connection, settings)
    except Exception:
        try:
            transaction = _load_transaction(transaction_id)
            _restore_snapshot(transaction["snapshot"])
        finally:
            _cancel_rollback(transaction_id)
            _transaction_path(transaction_id).unlink(missing_ok=True)
        raise
    return {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "expires_at": (
            datetime.now(UTC) + timedelta(seconds=rollback_seconds)
        ).isoformat(),
        "state": _state(settings.interface),
    }


def _confirm(transaction_id: str) -> dict[str, Any]:
    transaction = _load_transaction(transaction_id)
    _cancel_rollback(transaction_id)
    _transaction_path(transaction_id).unlink(missing_ok=True)
    requested = AgentNetworkSettings.model_validate(transaction["requested"])
    return _state(requested.interface)


def _rollback(transaction_id: str) -> dict[str, Any]:
    transaction = _load_transaction(transaction_id)
    snapshot = transaction.get("snapshot")
    if not isinstance(snapshot, dict):
        raise NetworkHelperError("Network transaction snapshot is invalid")
    _restore_snapshot(snapshot)
    _cancel_rollback(transaction_id)
    _transaction_path(transaction_id).unlink(missing_ok=True)
    return _state(str(snapshot["interface"]))


def parse_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ohana-agent-network-helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--rollback-seconds", type=int, default=90)
    confirm_parser = subparsers.add_parser("confirm")
    confirm_parser.add_argument("transaction_id")
    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("transaction_id")
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    try:
        parsed = parse_arguments(arguments)
        if parsed.command == "status":
            result = _state()
        elif parsed.command == "apply":
            result = _apply(parsed.rollback_seconds)
        elif parsed.command == "confirm":
            result = _confirm(parsed.transaction_id)
        else:
            result = _rollback(parsed.transaction_id)
    except Exception as error:  # Helper must return one concise root-owned error.
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
