"""Local chrony state and its restricted restart request.

The Agent never restarts chrony itself: it writes a request file that a
systemd path unit installed by Ohana-Installer watches. That unit can only
restart ``chrony.service``; the request content grants nothing else.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

CHRONY_UNIT = "chrony.service"
SYSTEMCTL_PATH = Path("/usr/bin/systemctl")


def chrony_status(
    *,
    systemctl_path: Path = SYSTEMCTL_PATH,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Read whether the local chrony unit is active, without privileges."""
    if not systemctl_path.is_file():
        raise FileNotFoundError("systemctl est indisponible sur cet hôte")
    result = runner(
        [str(systemctl_path), "is-active", CHRONY_UNIT],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    state = (result.stdout or "").strip()[:40] or "unknown"
    active = state == "active"
    return {
        "success": active,
        "unit": CHRONY_UNIT,
        "service_active": active,
        "state": state,
        "message": f"{CHRONY_UNIT} : {state}",
    }


class ChronyRestartRequester:
    """Trigger the installed restricted chrony helper."""

    def __init__(self, *, request_path: Path, path_unit: Path) -> None:
        self.request_path = request_path
        self.path_unit = path_unit

    def request_restart(self) -> None:
        if not self.path_unit.is_file():
            raise RuntimeError(
                "Le mécanisme privilégié de redémarrage de chrony n’est pas "
                "installé ; relancer Ohana-Installer sur cet hôte"
            )
        content = json.dumps(
            {"schema_version": 1, "requested_at_ns": time.time_ns()},
            separators=(",", ":"),
        )
        self.request_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{self.request_path.name}.",
                suffix=".tmp",
                dir=self.request_path.parent,
                delete=False,
            ) as temporary_file:
                temporary_file.write(content + "\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, self.request_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
