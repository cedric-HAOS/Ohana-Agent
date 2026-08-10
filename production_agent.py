"""Long-running Ohana-Agent production runtime."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, RLock
from time import monotonic
from typing import Any, Protocol

from configuration.infrastructure import InfrastructureConfig
from observer.exporters import (
    VisionClient,
    VisionClientError,
)
from scheduler import Scheduler

LOGGER = logging.getLogger(__name__)


class AdministrationRuntime(Protocol):
    """Lifecycle exposed by the optional administration endpoint."""

    def start(self) -> None:
        """Start accepting administration requests."""

    def stop(self) -> None:
        """Stop accepting administration requests."""


class TeleinformationIngestionRuntime(Protocol):
    """Lifecycle exposed by the direct teleinformation receiver."""

    def start(self) -> None:
        """Start accepting teleinfo2mqtt frames."""

    def stop(self) -> None:
        """Stop accepting teleinfo2mqtt frames."""


class HomeAssistantPublisherRuntime(Protocol):
    """Lifecycle exposed by the MQTT Home Assistant publisher."""

    def start(self) -> None:
        """Connect and publish MQTT Discovery."""

    def tick(self) -> None:
        """Publish a heartbeat when it becomes due."""

    def stop(self) -> None:
        """Publish the offline state and disconnect."""


class VisionExportRuntime(Protocol):
    """Lifecycle exposed by the durable Vision observation client."""

    def start(self) -> None:
        """Start retrying queued observations."""

    def stop(self) -> None:
        """Stop retrying and close durable storage."""


@dataclass(slots=True)
class ProductionAgent:
    """Run the configured Ohana-Agent scheduler continuously."""

    scheduler: Scheduler
    vision_client: VisionClient | None = None
    infrastructure_payload: dict[str, Any] | None = None
    tick_interval_seconds: float = 1.0
    infrastructure_retry_seconds: float = 10.0
    infrastructure_refresh_seconds: float = 300.0
    administration_runtime: AdministrationRuntime | None = None
    teleinformation_ingestion_runtime: TeleinformationIngestionRuntime | None = None
    home_assistant_publisher: HomeAssistantPublisherRuntime | None = None
    vision_export_runtime: VisionExportRuntime | None = None
    infrastructure_reconfigure: Callable[[InfrastructureConfig], None] | None = None
    monotonic_clock: Callable[[], float] = field(
        default=monotonic,
        repr=False,
    )
    _stop_event: Event = field(
        default_factory=Event,
        init=False,
        repr=False,
    )
    _infrastructure_synchronized: bool = field(
        default=False,
        init=False,
        repr=False,
    )
    _next_infrastructure_refresh_at: float | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _runtime_lock: RLock = field(
        default_factory=RLock,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate runtime settings."""
        if self.tick_interval_seconds <= 0:
            raise ValueError("tick_interval_seconds must be greater than zero.")

        if self.infrastructure_retry_seconds <= 0:
            raise ValueError("infrastructure_retry_seconds must be greater than zero.")

        if self.infrastructure_refresh_seconds <= 0:
            raise ValueError(
                "infrastructure_refresh_seconds must be greater than zero."
            )

        client_is_configured = self.vision_client is not None
        payload_is_configured = self.infrastructure_payload is not None

        if client_is_configured != payload_is_configured:
            raise ValueError(
                "vision_client and infrastructure_payload must be configured together."
            )

    @property
    def running(self) -> bool:
        """Return whether the production agent is running."""
        return (
            self.scheduler.running
            and self._infrastructure_synchronized
            and not self._stop_event.is_set()
        )

    @property
    def infrastructure_synchronized(self) -> bool:
        """Return whether Vision accepted the infrastructure snapshot."""
        return self._infrastructure_synchronized

    def start(self) -> None:
        """Synchronize Vision and start the scheduler when possible."""
        if self.scheduler.running:
            return

        self._stop_event.clear()
        self._start_administration()
        self._start_teleinformation_ingestion()
        self._start_home_assistant_publisher()
        self._start_vision_export()

        if not self._synchronize_infrastructure():
            return

        self._start_scheduler()

    def tick(self) -> None:
        """Execute one scheduler iteration."""
        with self._runtime_lock:
            results = self.scheduler.tick()

            for result in results:
                if result.success:
                    LOGGER.info(
                        "Scheduled task completed: %s",
                        result.command,
                    )
                else:
                    LOGGER.error(
                        "Scheduled task failed: %s — %s",
                        result.command,
                        result.error or "unknown error",
                    )

            self._tick_home_assistant_publisher()

    def run(self) -> None:
        """Run until a stop request is received."""
        self._stop_event.clear()
        self._start_administration()
        self._start_teleinformation_ingestion()
        self._start_home_assistant_publisher()
        self._start_vision_export()

        try:
            while not self._stop_event.is_set():
                if not self._infrastructure_synchronized:
                    if not self._synchronize_infrastructure():
                        self._tick_home_assistant_publisher()

                        if self._stop_event.wait(self.infrastructure_retry_seconds):
                            break

                        continue

                if not self.scheduler.running:
                    self._start_scheduler()

                if self._stop_event.wait(self.tick_interval_seconds):
                    break

                if self._infrastructure_refresh_due():
                    if not self._synchronize_infrastructure():
                        if self._stop_event.wait(self.infrastructure_retry_seconds):
                            break

                        continue

                self.tick()
        finally:
            self.stop()

    def request_stop(self) -> None:
        """Request a graceful shutdown."""
        LOGGER.info("Ohana-Agent shutdown requested.")
        self._stop_event.set()

    def stop(self) -> None:
        """Stop the scheduler and administration endpoint."""
        if self.scheduler.running:
            self.scheduler.stop()

        if self.administration_runtime is not None:
            self.administration_runtime.stop()

        if self.teleinformation_ingestion_runtime is not None:
            self.teleinformation_ingestion_runtime.stop()

        if self.home_assistant_publisher is not None:
            self.home_assistant_publisher.stop()

        if self.vision_export_runtime is not None:
            self.vision_export_runtime.stop()

        self._infrastructure_synchronized = False
        self._next_infrastructure_refresh_at = None
        self._stop_event.set()
        LOGGER.info("Ohana-Agent stopped.")

    def update_infrastructure_payload(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Replace and immediately synchronize the Agent-owned configuration."""
        with self._runtime_lock:
            self.infrastructure_payload = payload

            if self.vision_client is not None:
                self._synchronize_infrastructure()

    def apply_plugin_configuration(
        self,
        reconfigure: Callable[[], None],
    ) -> None:
        """Apply one plugin reconfiguration outside concurrent scheduler ticks."""
        with self._runtime_lock:
            reconfigure()

    def replace_teleinformation_ingestion_runtime(
        self,
        runtime: TeleinformationIngestionRuntime | None,
    ) -> None:
        """Replace the direct receiver while plugin configuration is applied."""
        with self._runtime_lock:
            previous = self.teleinformation_ingestion_runtime
            was_running = bool(
                previous is not None and getattr(previous, "running", False)
            )
            if previous is not None:
                previous.stop()
            self.teleinformation_ingestion_runtime = runtime
            if runtime is not None and (was_running or self.scheduler.running):
                runtime.start()

    def apply_infrastructure_configuration(
        self,
        configuration: InfrastructureConfig,
        payload: dict[str, Any],
    ) -> None:
        """Reconfigure observations and publish a new infrastructure snapshot."""
        with self._runtime_lock:
            scheduler_was_running = self.scheduler.running

            if scheduler_was_running:
                self.scheduler.stop()

            if self.infrastructure_reconfigure is not None:
                self.infrastructure_reconfigure(configuration)

            self.infrastructure_payload = payload
            synchronized = self._synchronize_infrastructure()

            if scheduler_was_running and synchronized:
                self._start_scheduler()

    def _start_administration(self) -> None:
        if self.administration_runtime is not None:
            self.administration_runtime.start()

    def _start_teleinformation_ingestion(self) -> None:
        if self.teleinformation_ingestion_runtime is not None:
            self.teleinformation_ingestion_runtime.start()

    def _start_home_assistant_publisher(self) -> None:
        if self.home_assistant_publisher is not None:
            self.home_assistant_publisher.start()

    def _start_vision_export(self) -> None:
        if self.vision_export_runtime is not None:
            self.vision_export_runtime.start()

    def _tick_home_assistant_publisher(self) -> None:
        if self.home_assistant_publisher is not None:
            self.home_assistant_publisher.tick()

    def _start_scheduler(self) -> None:
        """Start observations after infrastructure synchronization."""
        self.scheduler.start()
        LOGGER.info("Ohana-Agent started.")

    def _synchronize_infrastructure(self) -> bool:
        """Send the complete infrastructure snapshot to Vision."""
        if self.vision_client is None:
            self._infrastructure_synchronized = True
            self._next_infrastructure_refresh_at = None
            return True

        if self.infrastructure_payload is None:
            raise RuntimeError(
                "Infrastructure payload is missing while "
                "Vision synchronization is enabled."
            )

        try:
            self.vision_client.send_infrastructure(self.infrastructure_payload)
        except VisionClientError as error:
            if self.scheduler.running:
                self.scheduler.stop()

            self._infrastructure_synchronized = False
            self._next_infrastructure_refresh_at = None

            LOGGER.warning(
                "Unable to synchronize infrastructure with Ohana-Vision: %s",
                error,
            )
            return False

        self._infrastructure_synchronized = True
        self._next_infrastructure_refresh_at = (
            self.monotonic_clock() + self.infrastructure_refresh_seconds
        )

        LOGGER.info("Infrastructure synchronized with Ohana-Vision.")
        return True

    def _infrastructure_refresh_due(self) -> bool:
        """Return whether the infrastructure snapshot must be refreshed."""
        if self._next_infrastructure_refresh_at is None:
            return False

        return self.monotonic_clock() >= self._next_infrastructure_refresh_at
