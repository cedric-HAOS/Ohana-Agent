"""Periodic check that the rclone iCloud session still works.

On 28 September the iCloud session stored in rclone.conf had expired (HTTP 421
"Invalid global session"). Nothing reported it until an update tried to copy
the age recovery identity. The check lists the remote root once an hour and
publishes the result, so Home Assistant can alert before a backup needs it.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

from ohana_agent.plugins.backup.config import BackupConfig

LOGGER = logging.getLogger(__name__)

PARIS = ZoneInfo("Europe/Paris")
DEFAULT_INTERVAL_SECONDS = 3600.0
_COMMAND_TIMEOUT_SECONDS = 90.0

_SESSION_EXPIRED = re.compile(
    r"invalid global session|\b421\b|\b401\b|\b403\b|two[- ]factor|2fa|"
    r"trust token|authenticat|unauthori[sz]ed|reconnect",
    re.IGNORECASE,
)
_UNREACHABLE = re.compile(
    r"no such host|dial tcp|i/o timeout|timeout|network is unreachable|"
    r"connection refused|connection reset|temporary failure in name resolution",
    re.IGNORECASE,
)
_NOT_CONFIGURED = re.compile(
    r"didn't find section in config file|config file .* not found",
    re.IGNORECASE,
)
_SECRETS = re.compile(
    r"(password|token|cookie|session[_-]?id|trust)[\"'=: ]+[^\s,\"']+",
    re.IGNORECASE,
)

STATES = ("connected", "session_expired", "unreachable", "not_configured", "error")


@dataclass(frozen=True, slots=True)
class ICloudConnectivityStatus:
    """Home Assistant payload for the iCloud session of the Agent host."""

    state: str
    connected: bool
    remote: str
    checked_at: str
    last_success_at: str | None
    detail: str | None

    def to_json(self) -> str:
        """Serialize with stable compact JSON."""
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))


def classify_failure(detail: str) -> str:
    """Map an rclone failure message to a connectivity state."""
    if _NOT_CONFIGURED.search(detail):
        return "not_configured"
    if _SESSION_EXPIRED.search(detail):
        return "session_expired"
    if _UNREACHABLE.search(detail):
        return "unreachable"
    return "error"


def _safe_detail(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    return _SECRETS.sub(r"\1=***", lines[-1])[:300]


class ICloudConnectivityProbe:
    """List the configured iCloud remote root with rclone."""

    def __init__(
        self,
        config: BackupConfig,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        now: Callable[[], datetime] = lambda: datetime.now(PARIS),
    ) -> None:
        self.config = config
        self._runner = runner
        self._now = now
        self._last_success_at: str | None = None

    @property
    def remote(self) -> str:
        return f"{self.config.rclone_remote.partition(':')[0]}:"

    def check(self) -> ICloudConnectivityStatus:
        """Run one bounded check; never raises."""
        state, detail = self._run()
        checked_at = self._now().astimezone(PARIS).isoformat(timespec="seconds")
        if state == "connected":
            self._last_success_at = checked_at
        return ICloudConnectivityStatus(
            state=state,
            connected=state == "connected",
            remote=self.remote,
            checked_at=checked_at,
            last_success_at=self._last_success_at,
            detail=detail,
        )

    def _run(self) -> tuple[str, str | None]:
        if not Path(self.config.rclone_binary).is_file():
            return "not_configured", f"rclone absent : {self.config.rclone_binary}"
        if not Path(self.config.rclone_config_path).is_file():
            return (
                "not_configured",
                f"configuration rclone absente : {self.config.rclone_config_path}",
            )
        command = [
            self.config.rclone_binary,
            "lsd",
            self.remote,
            "--max-depth",
            "1",
            "--config",
            self.config.rclone_config_path,
            "--retries",
            "1",
            "--low-level-retries",
            "1",
            "--contimeout",
            "20s",
            "--timeout",
            "60s",
            "--log-level",
            "ERROR",
        ]
        try:
            result = self._runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return "unreachable", "iCloud n'a pas répondu dans le délai imparti"
        except OSError as error:
            return "error", _safe_detail(str(error))
        if result.returncode == 0:
            return "connected", None
        detail = _safe_detail(result.stderr or result.stdout or "") or (
            f"rclone a échoué (code {result.returncode})"
        )
        return classify_failure(detail), detail


class ICloudConnectivityReporter:
    """Check hourly in a background thread and deliver the status to sinks."""

    def __init__(
        self,
        probe: ICloudConnectivityProbe,
        *,
        sinks: tuple[Callable[[ICloudConnectivityStatus], None], ...],
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        monotonic_clock: Callable[[], float] = monotonic,
        thread_factory: Callable[..., Any] = Thread,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero.")
        self.probe = probe
        self._sinks = sinks
        self._interval_seconds = interval_seconds
        self._monotonic_clock = monotonic_clock
        self._thread_factory = thread_factory
        self._lock = Lock()
        self._running_check: Any | None = None
        self._next_check_at: float | None = None
        self._started = False

    @property
    def running(self) -> bool:
        return self._started

    def start(self) -> None:
        """Check once now, then every interval."""
        if self._started:
            return
        self._started = True
        self._next_check_at = self._monotonic_clock()
        self.tick()

    def tick(self) -> None:
        """Start a check when due; a slow rclone never blocks the scheduler."""
        if not self._started:
            return
        now = self._monotonic_clock()
        with self._lock:
            if self._next_check_at is not None and now < self._next_check_at:
                return
            if self._running_check is not None and self._running_check.is_alive():
                return
            self._next_check_at = now + self._interval_seconds
            self._running_check = self._thread_factory(
                target=self._check,
                name="ohana-icloud-connectivity",
                daemon=True,
            )
            self._running_check.start()

    def stop(self) -> None:
        self._started = False
        self._next_check_at = None

    def update_config(self, config: BackupConfig) -> None:
        """Use a new backup configuration and check it at the next tick."""
        self.probe.config = config
        with self._lock:
            self._next_check_at = self._monotonic_clock()

    def _check(self) -> None:
        status = self.probe.check()
        if not status.connected:
            LOGGER.warning(
                "iCloud connectivity check: %s (%s)", status.state, status.detail
            )
        for sink in self._sinks:
            try:
                sink(status)
            except Exception as error:
                LOGGER.warning("Unable to publish iCloud connectivity: %s", error)
