"""Restricted root helper for applying dnsmasq DHCP configuration updates."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

REQUEST_PATH = Path("/run/ohana-agent/dhcp-reload.request")
LEASES_PATH = Path("/var/lib/misc/dnsmasq.leases")
SYSTEMCTL = Path("/usr/bin/systemctl")
DNSMASQ_SERVICE = "dnsmasq.service"
MAC_ADDRESS_PATTERN = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
MAXIMUM_REQUEST_BYTES = 64 * 1024


class DHCPReloadError(RuntimeError):
    """Raised when a privileged dnsmasq reload cannot be completed safely."""


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _read_request(path: Path) -> set[str]:
    if path.is_symlink() or not path.is_file():
        raise DHCPReloadError("DHCP reload request is not a regular file")

    if path.stat().st_size > MAXIMUM_REQUEST_BYTES:
        raise DHCPReloadError("DHCP reload request is too large")

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DHCPReloadError(f"Invalid DHCP reload request: {error}") from error

    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise DHCPReloadError("Unsupported DHCP reload request")

    raw_macs = document.get("stale_lease_macs")
    if not isinstance(raw_macs, list) or not all(
        isinstance(mac, str) for mac in raw_macs
    ):
        raise DHCPReloadError("Invalid stale DHCP lease list")

    macs = {mac.upper() for mac in raw_macs}
    if any(MAC_ADDRESS_PATTERN.fullmatch(mac) is None for mac in macs):
        raise DHCPReloadError("Invalid MAC address in DHCP reload request")

    return macs


def _atomic_write(path: Path, content: str, source_stat: os.stat_result) -> None:
    temporary_path: Path | None = None

    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            newline="\n",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)

        os.chmod(temporary_path, stat.S_IMODE(source_stat.st_mode))
        os.chown(temporary_path, source_stat.st_uid, source_stat.st_gid)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _purge_stale_leases(path: Path, stale_macs: set[str]) -> int:
    if not stale_macs or not path.exists():
        return 0

    if path.is_symlink() or not path.is_file():
        raise DHCPReloadError("dnsmasq leases path is not a regular file")

    source_stat = path.stat()
    lines = path.read_text(encoding="utf-8").splitlines()
    retained_lines: list[str] = []
    removed = 0

    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[1].upper() in stale_macs:
            removed += 1
            continue
        retained_lines.append(line)

    if removed:
        content = "\n".join(retained_lines)
        if retained_lines:
            content += "\n"
        _atomic_write(path, content, source_stat)

    return removed


def _systemctl(action: str, runner: CommandRunner) -> None:
    command = [str(SYSTEMCTL), action, DNSMASQ_SERVICE]

    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DHCPReloadError(f"Unable to {action} dnsmasq: {error}") from error

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise DHCPReloadError(detail or f"Unable to {action} dnsmasq")


def apply_reload(
    *,
    request_path: Path = REQUEST_PATH,
    leases_path: Path = LEASES_PATH,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    """Stop dnsmasq, remove only conflicting leases, and start it again."""
    stale_macs = _read_request(request_path)
    _systemctl("stop", runner)

    try:
        removed = _purge_stale_leases(leases_path, stale_macs)
    finally:
        _systemctl("start", runner)

    return {
        "schema_version": 1,
        "removed_leases": removed,
    }


def main() -> int:
    try:
        result = apply_reload()
    except Exception as error:  # Root helper must return one concise error.
        print(str(error), file=sys.stderr)
        return 1

    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
