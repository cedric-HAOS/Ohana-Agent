"""Phase 10: read the latest published archives again, in the background.

A new archive is read once; the same archive is read again every
``recheck_after_days`` days to catch a silent alteration on the remote. A slow
or unreachable remote never blocks the scheduler: each pass runs in its own
daemon thread and only one runs at a time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Lock, Thread
from time import monotonic
from typing import Any

from ohana_agent.plugins.backup.archive_verifier import ArchiveCheck, ArchiveVerifier
from ohana_agent.plugins.backup.config import BackupConfig
from ohana_agent.tsunade.local_time import paris_now, to_paris

LOGGER = logging.getLogger(__name__)
DEFAULT_INTERVAL_SECONDS = 24 * 3600
DEFAULT_FIRST_DELAY_SECONDS = 30 * 60
RECHECK_AFTER_DAYS = 7


class ArchiveIntegrityReporter:
    """Verify the latest archive of every backup target and record the outcome."""

    def __init__(
        self,
        verifier: ArchiveVerifier,
        *,
        record: Callable[[ArchiveCheck], None],
        last_check: Callable[[str], dict[str, Any] | None],
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        first_delay_seconds: float = DEFAULT_FIRST_DELAY_SECONDS,
        recheck_after_days: int = RECHECK_AFTER_DAYS,
        monotonic_clock: Callable[[], float] = monotonic,
        thread_factory: Callable[..., Any] = Thread,
        now: Callable[[], datetime] = paris_now,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero.")
        self.verifier = verifier
        self._record = record
        self._last_check = last_check
        self._interval = interval_seconds
        self._first_delay = first_delay_seconds
        self._recheck_after = timedelta(days=recheck_after_days)
        self._monotonic = monotonic_clock
        self._thread_factory = thread_factory
        self._now = now
        self._lock = Lock()
        self._thread: Any | None = None
        self._next_at: float | None = None
        self._started = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._next_at = self._monotonic() + self._first_delay

    def stop(self) -> None:
        self._started = False
        self._next_at = None

    def tick(self) -> None:
        """Start the daily pass when it is due."""
        if not self._started:
            return
        now = self._monotonic()
        with self._lock:
            if self._next_at is not None and now < self._next_at:
                return
            if self.running:
                return
            self._next_at = now + self._interval
            self._launch(None, forced=False)

    def update_config(self, config: BackupConfig) -> None:
        self.verifier.config = config

    def request(self, target: str | None = None) -> list[str]:
        """Verify now, whatever the previous outcome; returns the targets started."""
        known = self.verifier.targets()
        if target is not None and target not in known:
            raise ValueError(f"Unknown backup target: {target!r}.")
        with self._lock:
            if self.running:
                return []
            selected = [target] if target else known
            self._launch(selected, forced=True)
            return selected

    def _launch(self, targets: list[str] | None, *, forced: bool) -> None:
        self._thread = self._thread_factory(
            target=self._run,
            args=(targets, forced),
            name="ohana-archive-integrity",
            daemon=True,
        )
        self._thread.start()

    def _run(self, targets: list[str] | None, forced: bool) -> None:
        for target in targets or self.verifier.targets():
            try:
                check = self.verifier.verify(
                    target, skip=None if forced else self._recent_ok_for(target)
                )
                if check is None:
                    continue
                self._record(check)
                if check.outcome != "ok":
                    LOGGER.warning(
                        "Archive check %s: %s (%s)",
                        target,
                        check.outcome,
                        check.detail,
                    )
            except Exception:  # noqa: BLE001 - one target never stops the others.
                LOGGER.exception("Unable to verify the %s archive", target)

    def _recent_ok_for(self, target: str) -> Callable[[str], bool]:
        def skip(backup_ref: str) -> bool:
            last = self._last_check(target)
            if last is None or last["outcome"] != "ok":
                return False
            if last["backup_ref"] != backup_ref:
                return False
            checked = to_paris(datetime.fromisoformat(last["checked_at"]))
            return self._now() - checked < self._recheck_after

        return skip
