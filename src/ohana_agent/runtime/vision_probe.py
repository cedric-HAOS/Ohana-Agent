"""Phase 5: whether Ohana-Vision answers and still ingests, seen by the Agent.

The probe polls Vision's /api/runtime/vitals from its own thread: Vision once
took more than 10 s to answer on INFRA-01's SD card, and host health runs on
the Agent's main loop. Host health only reads the last answer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ohana_agent.tsunade.local_time import paris_now

LOGGER = logging.getLogger(__name__)

VITALS_PATH = "/api/runtime/vitals"
# The Agent delivers several observations a minute: five silent minutes mean
# Vision no longer ingests, whatever the reason.
INGESTION_SILENCE_LIMIT_SECONDS = 300


def vitals_url(observation_url: str) -> str:
    """Derive Vision's vitals endpoint from its observation endpoint."""
    parts = urlsplit(observation_url)
    return urlunsplit((parts.scheme, parts.netloc, VITALS_PATH, "", ""))


def _http_fetch(url: str, timeout_seconds: float) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


class VisionVitalsProbe:
    """Keep the latest Vision vital state, refreshed in the background."""

    def __init__(
        self,
        url: str,
        *,
        interval_seconds: float = 60.0,
        timeout_seconds: float = 5.0,
        fetch: Callable[[str, float], dict[str, Any]] = _http_fetch,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        self.url = url
        self.interval_seconds = interval_seconds
        self.timeout_seconds = timeout_seconds
        self._fetch = fetch
        self._monotonic_clock = monotonic_clock
        self._latest: dict[str, Any] | None = None
        self._latest_at: float | None = None
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run, name="ohana-vision-probe", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.timeout_seconds + 1)
            self._thread = None

    def check_now(self) -> dict[str, Any]:
        """Measure Vision once, record and return the result."""
        checked_at = paris_now().isoformat()
        try:
            document = self._fetch(self.url, self.timeout_seconds)
            if not isinstance(document, dict):
                raise ValueError("Vision vitals must be a JSON object")
        except Exception as error:  # noqa: BLE001 - any failure is unavailability.
            result: dict[str, Any] = {
                "available": False,
                "error": type(error).__name__,
                "ingestion_silence_seconds": None,
                "last_ingested_at": None,
                "started_at": None,
            }
        else:
            silence = document.get("ingestion_silence_seconds")
            result = {
                "available": document.get("state") == "running",
                "error": None
                if document.get("state") == "running"
                else f"state {document.get('state')}",
                "ingestion_silence_seconds": silence
                if isinstance(silence, int)
                else None,
                "last_ingested_at": document.get("last_ingested_at"),
                "started_at": document.get("started_at"),
            }
            # Vision >= 1.32: its version and database size (Phase 5 detail).
            storage = document.get("storage")
            if isinstance(document.get("version"), str):
                result["version"] = document["version"]
            if isinstance(storage, dict) and isinstance(
                storage.get("database_bytes"), int
            ):
                result["database_bytes"] = storage["database_bytes"]
        result["checked_at"] = checked_at
        with self._lock:
            self._latest = result
            self._latest_at = self._monotonic_clock()
        return dict(result)

    def latest(self) -> dict[str, Any] | None:
        """Return the last measure, or None when it is too old to trust."""
        with self._lock:
            if self._latest is None or self._latest_at is None:
                return None
            if self._monotonic_clock() - self._latest_at > 3 * self.interval_seconds:
                return None
            return dict(self._latest)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.check_now()
            if self._stop_event.wait(self.interval_seconds):
                return


def vision_failures(state: dict[str, Any] | None) -> tuple[str, ...]:
    """Return the host.health reasons a Vision measure supports."""
    if state is None:
        return ()
    if state.get("available") is False:
        return ("vision_http_unavailable",)
    silence = state.get("ingestion_silence_seconds")
    if isinstance(silence, int) and silence > INGESTION_SILENCE_LIMIT_SECONDS:
        return ("vision_ingestion_stale",)
    return ()
