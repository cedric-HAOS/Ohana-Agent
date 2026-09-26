"""Outcome of a privileged Installer helper triggered by a request file.

The Agent never runs the privileged action itself: it writes a request that a
systemd path unit turns into one ``oneshot`` service run. Reading that
service's result needs no privilege, so a supervised repair can report why a
helper failed (for example a masked unit) instead of only learning it from
Shikamaru's next observation.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

SYSTEMCTL_PATH = Path("/usr/bin/systemctl")
HELPER_WAIT_SECONDS = 15.0


class HelperOutcome:
    """Wait for the next run of one helper service and raise if it failed."""

    def __init__(
        self,
        service: str,
        target_unit: str,
        *,
        systemctl_path: Path = SYSTEMCTL_PATH,
        runner: Callable[..., Any] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wait_seconds: float = HELPER_WAIT_SECONDS,
    ) -> None:
        self.service = service
        self.target_unit = target_unit
        self.systemctl_path = systemctl_path
        self.runner = runner
        self.sleep = sleep
        self.monotonic = monotonic
        self.wait_seconds = wait_seconds

    def _show(self, unit: str, *properties: str) -> dict[str, str]:
        result = self.runner(
            [
                str(self.systemctl_path),
                "show",
                unit,
                *(f"--property={name}" for name in properties),
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

    def baseline(self) -> int | None:
        """Last exit of the helper before the request, or None if unreadable."""
        if not self.systemctl_path.is_file():
            return None
        try:
            value = self._show(self.service, "ExecMainExitTimestampMonotonic").get(
                "ExecMainExitTimestampMonotonic", "0"
            )
            return int(value or 0)
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def wait(self, baseline: int | None) -> None:
        """Raise with the cause if the helper run after ``baseline`` failed."""
        if baseline is None:
            return
        deadline = self.monotonic() + self.wait_seconds
        while True:
            try:
                state = self._show(
                    self.service,
                    "ActiveState",
                    "Result",
                    "ExecMainStatus",
                    "ExecMainExitTimestampMonotonic",
                )
            except (OSError, subprocess.SubprocessError):
                return
            try:
                exited = int(state.get("ExecMainExitTimestampMonotonic") or 0)
            except ValueError:
                exited = 0
            if exited > baseline and state.get("ActiveState") in {
                "inactive",
                "failed",
            }:
                if state.get("Result") == "success":
                    return
                raise RuntimeError(self._failure(state))
            if self.monotonic() >= deadline:
                LOGGER.warning(
                    "%s did not finish within %.0f s; Shikamaru verifies the result",
                    self.service,
                    self.wait_seconds,
                )
                return
            self.sleep(0.5)

    def _failure(self, state: dict[str, str]) -> str:
        message = (
            f"L’assistant {self.service} a échoué "
            f"({state.get('Result') or 'inconnu'}, code "
            f"{state.get('ExecMainStatus') or '?'})"
        )
        try:
            target = self._show(
                self.target_unit, "LoadState", "UnitFileState", "ActiveState"
            )
        except (OSError, subprocess.SubprocessError):
            return message
        if target.get("LoadState") == "masked" or target.get("UnitFileState") == (
            "masked"
        ):
            return f"{message} : {self.target_unit} est masqué"
        details = ", ".join(
            f"{key}={value}" for key, value in sorted(target.items()) if value
        )
        return f"{message} : {self.target_unit} {details}" if details else message
