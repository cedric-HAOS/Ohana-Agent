"""Bounded read-only inspection of the installed systemd oneshot and timer."""

import subprocess
from time import monotonic


class SystemdSyncProbe:
    def inspect(self, *, maximum_age_seconds: int) -> dict[str, object]:
        timer = self._show("adguardhome-sync.timer")
        service = self._show("adguardhome-sync.service")
        evidence: dict[str, object] = {
            "timer_active": timer.get("ActiveState") == "active",
            "service_active_state": service.get("ActiveState"),
            "cycle_result": service.get("Result"),
        }
        if any(unit.get("LoadState") != "loaded" for unit in (timer, service)):
            return {**evidence, "state": "units_missing"}
        if not evidence["timer_active"]:
            return {**evidence, "state": "timer_inactive"}
        now = monotonic()
        if service.get("ActiveState") in {"activating", "active", "deactivating"}:
            start = int(service.get("ExecMainStartTimestampMonotonic", "0")) / 1e6
            age = now - start
            state = (
                "running" if start > 0 and 0 <= age <= maximum_age_seconds else "stale"
            )
            return {**evidence, "state": state, "running_age_seconds": max(0, age)}
        if service.get("Result") != "success" or service.get("ExecMainStatus") != "0":
            return {**evidence, "state": "cycle_failed"}
        exited = int(service.get("ExecMainExitTimestampMonotonic", "0")) / 1e6
        if exited <= 0:
            return {**evidence, "state": "never_completed"}
        age = now - exited
        if age < 0:
            raise ValueError("Invalid systemd timestamp")
        return {
            **evidence,
            "state": "fresh" if age <= maximum_age_seconds else "stale",
            "last_completed_age_seconds": age,
        }

    @staticmethod
    def _show(unit: str) -> dict[str, str]:
        process = subprocess.run(
            [
                "systemctl",
                "show",
                unit,
                "--no-pager",
                "--property=LoadState,ActiveState,Result,ExecMainStatus,"
                "ExecMainStartTimestampMonotonic,ExecMainExitTimestampMonotonic",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        return dict(
            line.split("=", 1) for line in process.stdout.splitlines() if "=" in line
        )
