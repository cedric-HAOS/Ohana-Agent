"""Read-only state of the operating system's package updates.

The Agent only reads: ``apt-get -s`` simulates the upgrade without a lock or a
privilege, and the other facts are files that Debian publishes world-readable.
Refreshing the package lists and applying the upgrade need root and belong to
an Installer helper (see ``SystemUpdateRequester``), never to the Agent.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from ohana_agent.tsunade.local_time import paris_instant

APT_GET_PATH = Path("/usr/bin/apt-get")
APT_LISTS_DIRECTORY = Path("/var/lib/apt/lists")
APT_PERIODIC_STAMP = Path("/var/lib/apt/periodic/update-success-stamp")
APT_HISTORY_PATH = Path("/var/log/apt/history.log")
REBOOT_REQUIRED_PATH = Path("/var/run/reboot-required")
REBOOT_REQUIRED_PACKAGES_PATH = Path("/var/run/reboot-required.pkgs")

# Package lists older than this no longer say what is really pending.
STALE_LISTS_AFTER_DAYS = 3.0
MAX_LISTED_PACKAGES = 60

_INST_LINE = re.compile(
    r"^Inst (?P<name>\S+)(?: \[(?P<old>[^\]]+)\])? "
    r"\((?P<new>\S+) (?P<origin>.*?)(?: \[[^\]]+\])?\)\s*$"
)
_HELD_BACK_HEADER = "The following packages have been kept back:"


def _paris(timestamp: float) -> str:
    return paris_instant(datetime.fromtimestamp(timestamp, UTC)).isoformat()


def parse_simulated_upgrade(output: str) -> dict[str, Any]:
    """Turn ``apt-get -s upgrade`` output into pending and held-back packages."""
    pending: list[dict[str, Any]] = []
    held_back: list[str] = []
    in_held_back = False
    for line in output.splitlines():
        if line.startswith(_HELD_BACK_HEADER):
            in_held_back = True
            continue
        if in_held_back:
            if line.startswith("  "):
                held_back.extend(line.split())
                continue
            in_held_back = False
        match = _INST_LINE.match(line)
        if match is None:
            continue
        origin = match["origin"]
        pending.append(
            {
                "name": match["name"],
                "installed_version": match["old"],
                "candidate_version": match["new"],
                "origin": origin,
                "security": "security" in origin.lower(),
                "new_package": match["old"] is None,
            }
        )
    return {"pending": pending, "held_back": held_back}


def _package_lists_age(
    *, lists_directory: Path, periodic_stamp: Path, now: float
) -> tuple[float | None, float | None]:
    """Most recent successful ``apt-get update`` as (timestamp, age in days)."""
    candidates: list[float] = []
    try:
        if periodic_stamp.is_file():
            candidates.append(periodic_stamp.stat().st_mtime)
        for release in lists_directory.glob("*_InRelease"):
            candidates.append(release.stat().st_mtime)
        for release in lists_directory.glob("*_Release"):
            candidates.append(release.stat().st_mtime)
    except OSError:
        return None, None
    if not candidates:
        return None, None
    refreshed = max(candidates)
    return refreshed, max(0.0, (now - refreshed) / 86400)


def _reboot_state(reboot_path: Path, packages_path: Path) -> tuple[bool, list[str]]:
    try:
        required = reboot_path.is_file()
        packages = (
            sorted(
                {line.strip() for line in packages_path.read_text().splitlines()} - {""}
            )
            if required and packages_path.is_file()
            else []
        )
    except OSError:
        return False, []
    return required, packages


def _last_apt_run(history_path: Path) -> dict[str, Any] | None:
    """Last package-changing apt run, looking back through rotated logs."""
    for path in (history_path, Path(f"{history_path}.1"), Path(f"{history_path}.1.gz")):
        run = _last_apt_run_in(path)
        if run is not None:
            return run
    return None


def _last_apt_run_in(history_path: Path) -> dict[str, Any] | None:
    try:
        opener = gzip.open if history_path.suffix == ".gz" else open
        with opener(history_path, "rt", encoding="utf-8", errors="replace") as source:
            text = source.read()
    except OSError:
        return None
    last: dict[str, Any] | None = None
    for block in text.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.strip().splitlines() if ": " in line
        )
        if "Start-Date" not in fields:
            continue
        changed = [
            key for key in ("Install", "Upgrade", "Remove", "Purge") if fields.get(key)
        ]
        if not changed:
            continue
        last = {
            "started_at": fields["Start-Date"].strip(),
            "command": fields.get("Commandline", "").strip()[:200],
            "changes": {key: len(fields[key].split("), ")) for key in changed},
        }
    return last


def _verdict(
    *,
    stale: bool,
    security_count: int,
    pending_count: int,
    reboot_required: bool,
) -> tuple[str, str]:
    if stale:
        return (
            "stale_lists",
            "Les listes de paquets sont périmées : les mises à jour en attente "
            "ne sont pas connues.",
        )
    if security_count:
        return (
            "security_updates",
            f"{security_count} mise(s) à jour de sécurité en attente.",
        )
    if reboot_required:
        return "reboot_required", "Un redémarrage est nécessaire."
    if pending_count:
        return "updates_available", f"{pending_count} mise(s) à jour en attente."
    return "up_to_date", "Le système est à jour."


def read_system_updates(
    *,
    apt_get_path: Path = APT_GET_PATH,
    lists_directory: Path = APT_LISTS_DIRECTORY,
    periodic_stamp: Path = APT_PERIODIC_STAMP,
    history_path: Path = APT_HISTORY_PATH,
    reboot_path: Path = REBOOT_REQUIRED_PATH,
    reboot_packages_path: Path = REBOOT_REQUIRED_PACKAGES_PATH,
    runner: Callable[..., Any] = subprocess.run,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Describe pending package updates without any privilege."""
    if not apt_get_path.is_file():
        raise FileNotFoundError("apt-get est indisponible sur cet hôte")
    now = clock() if clock is not None else datetime.now(UTC).timestamp()
    result = runner(
        [
            str(apt_get_path),
            "-s",
            "-o",
            "Debug::NoLocking=1",
            "--with-new-pkgs",
            "upgrade",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        raise RuntimeError(
            "La simulation de mise à jour a échoué : "
            + ((result.stderr or "").strip()[:200] or f"code {result.returncode}")
        )
    simulation = parse_simulated_upgrade(result.stdout or "")
    pending = simulation["pending"]
    security_count = sum(1 for package in pending if package["security"])
    refreshed_at, age_days = _package_lists_age(
        lists_directory=lists_directory, periodic_stamp=periodic_stamp, now=now
    )
    stale = age_days is None or age_days > STALE_LISTS_AFTER_DAYS
    reboot_required, reboot_packages = _reboot_state(reboot_path, reboot_packages_path)
    status, message = _verdict(
        stale=stale,
        security_count=security_count,
        pending_count=len(pending),
        reboot_required=reboot_required,
    )
    # Security fixes first, then the rest, so a long list stays readable.
    ordered = sorted(
        pending, key=lambda package: (not package["security"], package["name"])
    )
    return {
        "status": status,
        "message": message,
        "pending_count": len(pending),
        "security_count": security_count,
        "kernel_pending": any(
            package["name"].startswith("linux-image-") for package in pending
        ),
        "packages": ordered[:MAX_LISTED_PACKAGES],
        "packages_truncated": len(ordered) > MAX_LISTED_PACKAGES,
        "held_back": simulation["held_back"][:MAX_LISTED_PACKAGES],
        "lists_refreshed_at": _paris(refreshed_at) if refreshed_at else None,
        "lists_age_days": round(age_days, 1) if age_days is not None else None,
        "lists_stale": stale,
        "reboot_required": reboot_required,
        "reboot_packages": reboot_packages,
        "last_apt_run": _last_apt_run(history_path),
        "read_at": _paris(now),
    }


SYSTEMCTL_PATH = Path("/usr/bin/systemctl")
REQUEST_DIRECTORY = Path("/run/ohana-agent")
SYSTEMD_DIRECTORY = Path("/etc/systemd/system")
UPDATE_ACTIONS = {
    # action -> (helper service, request file stem)
    "refresh": ("ohana-system-refresh.service", "system-refresh"),
    "upgrade": ("ohana-system-upgrade.service", "system-upgrade"),
}


class SystemUpdateRequester:
    """Ask the restricted Installer helpers to refresh or upgrade the packages.

    The Agent never runs apt: it writes a request that a systemd path unit
    turns into one ``oneshot`` root service whose command is fixed. The request
    content grants nothing, so it cannot choose the action or add an argument.
    """

    def __init__(
        self,
        *,
        request_directory: Path = REQUEST_DIRECTORY,
        systemd_directory: Path = SYSTEMD_DIRECTORY,
        systemctl_path: Path = SYSTEMCTL_PATH,
        runner: Callable[..., Any] = subprocess.run,
        clock: Callable[[], float] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.request_directory = request_directory
        self.systemd_directory = systemd_directory
        self.systemctl_path = systemctl_path
        self.runner = runner
        self.clock = clock or (lambda: datetime.now(UTC).timestamp())
        self.monotonic = monotonic or time.monotonic

    def installed(self) -> bool:
        """Whether the Installer provisioned both helpers on this host."""
        return (
            all(
                (self.systemd_directory / f"ohana-{stem}.path").is_file()
                for _service, stem in UPDATE_ACTIONS.values()
            )
            and self.systemctl_path.is_file()
        )

    def _show(self, service: str) -> dict[str, str]:
        result = self.runner(
            [
                str(self.systemctl_path),
                "show",
                service,
                "--property=ActiveState,Result,ExecMainStatus,"
                "ExecMainStartTimestampMonotonic,ExecMainExitTimestampMonotonic",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        values: dict[str, str] = {}
        for line in (result.stdout or "").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip()
        return values

    def _wall_time(self, monotonic_microseconds: str | None) -> str | None:
        """systemd stamps on CLOCK_MONOTONIC, which is ``time.monotonic`` on Linux."""
        try:
            stamp = int(monotonic_microseconds or 0)
        except ValueError:
            return None
        if stamp <= 0:
            return None
        return _paris(self.clock() - (self.monotonic() - stamp / 1_000_000))

    def status(self) -> dict[str, Any]:
        """Per action: never run, running, succeeded or failed (and when)."""
        if not self.installed():
            return {"installed": False}
        report: dict[str, Any] = {"installed": True}
        for action, (service, _stem) in UPDATE_ACTIONS.items():
            values = self._show(service)
            active = values.get("ActiveState", "")
            started = self._wall_time(values.get("ExecMainStartTimestampMonotonic"))
            finished = self._wall_time(values.get("ExecMainExitTimestampMonotonic"))
            if active in {"activating", "active", "reloading"}:
                state = "running"
            elif started is None:
                state = "never"
            elif values.get("Result") == "success":
                state = "succeeded"
            else:
                state = "failed"
            report[action] = {
                "state": state,
                "started_at": started,
                "finished_at": finished if state in {"succeeded", "failed"} else None,
                "result": values.get("Result") or None,
                "exit_status": values.get("ExecMainStatus") or None,
            }
        return report

    def request(self, action: str) -> dict[str, Any]:
        """Write the request for one action unless a helper is already running."""
        if action not in UPDATE_ACTIONS:
            raise ValueError(f"unknown system update action: {action}")
        status = self.status()
        if not status["installed"]:
            raise RuntimeError(
                "Les assistants de mise à jour système ne sont pas installés ; "
                "relancer Ohana-Installer sur cet hôte"
            )
        # apt takes one lock: a second request would only fail on it.
        if any(status[name]["state"] == "running" for name in UPDATE_ACTIONS):
            return {"started": False, "busy": True, "action": action}
        self._write_request(
            self.request_directory / f"{UPDATE_ACTIONS[action][1]}.request"
        )
        return {"started": True, "busy": False, "action": action}

    def _write_request(self, request_path: Path) -> None:
        content = json.dumps(
            {"schema_version": 1, "requested_at_ns": time.time_ns()},
            separators=(",", ":"),
        )
        request_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{request_path.name}.",
                suffix=".tmp",
                dir=request_path.parent,
                delete=False,
            ) as temporary_file:
                temporary_file.write(content + "\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, request_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
