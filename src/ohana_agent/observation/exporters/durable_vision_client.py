"""Vision client wrapper providing durable observation delivery."""

from __future__ import annotations

import logging
from collections import deque
from threading import Event, Lock, Thread
from typing import Any

from ohana_agent.observation.exporters.vision_client import VisionClient
from ohana_agent.observation.exporters.vision_client_error import VisionClientError
from ohana_agent.observation.exporters.vision_observation_outbox import (
    VisionObservationOutbox,
)

LOGGER = logging.getLogger(__name__)


class DurableVisionClient:
    """Queue observations locally and retry them in ingestion order."""

    def __init__(
        self,
        client: VisionClient,
        outbox: VisionObservationOutbox,
        *,
        retry_seconds: float = 10.0,
    ) -> None:
        if retry_seconds <= 0:
            raise ValueError("retry_seconds must be greater than zero.")

        self.client = client
        self.outbox = outbox
        self.retry_seconds = retry_seconds
        self._stop_event = Event()
        self._wake_event = Event()
        self._flush_lock = Lock()
        self._worker: Thread | None = None
        # Producers run on the Agent event loop: they never touch SQLite, whose
        # commits can wait seconds on a slow SD card.
        self._incoming: deque[dict[str, Any]] = deque()
        self._incoming_lock = Lock()

    @property
    def pending_count(self) -> int:
        """Return the current backlog size, persisted or not yet."""
        with self._incoming_lock:
            return len(self._incoming) + self.outbox.pending_count

    def start(self) -> None:
        """Start the background retry worker."""
        if self._worker is not None and self._worker.is_alive():
            return

        self._stop_event.clear()
        self._worker = Thread(
            target=self._run,
            name="ohana-vision-outbox",
            daemon=True,
        )
        self._worker.start()
        self._wake_event.set()

    def stop(self) -> None:
        """Stop retrying and close the durable outbox."""
        self._stop_event.set()
        self._wake_event.set()
        if self._worker is not None:
            self._worker.join()
            self._worker = None
        self._persist_incoming()
        self.outbox.close()

    def send_observation(self, payload: dict[str, Any]) -> None:
        """Queue an observation and wake the worker that persists and sends it."""
        if not str(payload.get("observation_id", "")).strip():
            raise ValueError("Vision observation payload must contain observation_id.")
        self._incoming.append(payload)
        self._wake_event.set()

    def send_infrastructure(self, payload: dict[str, Any]) -> None:
        """Synchronize infrastructure directly with Vision."""
        self.client.send_infrastructure(payload)

    def flush(self) -> int:
        """Deliver queued observations in order until Vision becomes unavailable."""
        delivered = 0
        with self._flush_lock:
            self._persist_incoming()
            while not self._stop_event.is_set():
                entry = self.outbox.oldest()
                if entry is None:
                    break

                try:
                    self.client.send_observation(entry.payload)
                except VisionClientError as error:
                    self.outbox.mark_failed(entry.observation_id, str(error))
                    LOGGER.warning(
                        "Unable to deliver observation %s to Ohana-Vision: %s",
                        entry.observation_id,
                        error,
                    )
                    break

                self.outbox.mark_delivered(entry.observation_id)
                delivered += 1

        return delivered

    def _persist_incoming(self) -> None:
        with self._incoming_lock:
            batch = list(self._incoming)
            self.outbox.enqueue_many(batch)
            # Appends made meanwhile stay queued for the next pass.
            for _ in batch:
                self._incoming.popleft()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._wake_event.wait(self.retry_seconds)
            self._wake_event.clear()
            if not self._stop_event.is_set():
                self.flush()
