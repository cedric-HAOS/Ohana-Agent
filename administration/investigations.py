"""Finite, authenticated and structured Tsunade investigation operations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field

from administration.jobs import DistributedJobRepository
from administration.models import AdministrationModel
from administration.plugins import PluginAdministrationRepository

LOGGER = logging.getLogger(__name__)


class InvestigationRequest(AdministrationModel):
    operation: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.]+$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=15, ge=1, le=60)
    incident_id: UUID | None = None


class InvestigationOperation(AdministrationModel):
    operation: str
    description: str
    permission: Literal["administration"] = "administration"
    parameters: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int


class InvestigationResult(AdministrationModel):
    investigation_id: UUID
    operation: str
    status: Literal["OK", "KO", "TIMEOUT"]
    started_at: datetime
    finished_at: datetime
    duration_seconds: float = Field(ge=0)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class InvestigationExecutor:
    """Execute only operations backed by existing Agent probes and plugin tests."""

    def __init__(
        self,
        *,
        plugins: PluginAdministrationRepository,
        host_health_reader: Callable[[], dict[str, Any]],
        jobs: DistributedJobRepository | None = None,
    ) -> None:
        self.plugins = plugins
        self.host_health_reader = host_health_reader
        self.jobs = jobs
        self._operations: dict[str, tuple[str, int, Callable[[], dict[str, Any]]]] = {
            "network.ping": (
                "Test configured network presence",
                15,
                lambda: self._test("network"),
            ),
            "dns.query": (
                "Test configured DNS resolution",
                15,
                lambda: self._test("dns"),
            ),
            "mqtt.status": (
                "Test configured MQTT round trip",
                20,
                lambda: self._test("mqtt"),
            ),
            "backup.status": ("Read backup runtime status", 5, self._backup_status),
            "memory.status": (
                "Read bounded host memory metrics",
                5,
                lambda: self._host("memory"),
            ),
            "cpu.status": (
                "Read bounded host CPU metrics",
                5,
                lambda: self._host("cpu"),
            ),
            "disk.usage": (
                "Read bounded root disk metrics",
                5,
                lambda: self._host("disk"),
            ),
            "service.status": (
                "Read monitored systemd unit state",
                5,
                lambda: self._host("services"),
            ),
        }

    def catalog(self) -> list[InvestigationOperation]:
        return [
            InvestigationOperation(
                operation=name,
                description=description,
                timeout_seconds=timeout,
            )
            for name, (description, timeout, _handler) in sorted(
                self._operations.items()
            )
        ]

    def execute(self, payload: dict[str, Any]) -> InvestigationResult:
        request = InvestigationRequest.model_validate(payload)
        definition = self._operations.get(request.operation)
        if definition is None:
            raise ValueError(
                f"Investigation operation is not authorized: {request.operation}"
            )
        if request.parameters:
            raise ValueError(
                "This investigation operation accepts no arbitrary parameters"
            )
        _description, maximum_timeout, handler = definition
        if request.timeout_seconds > maximum_timeout:
            raise ValueError(
                f"{request.operation} timeout cannot exceed {maximum_timeout} seconds"
            )
        investigation_id = uuid4()
        started_at = datetime.now(UTC)
        started = monotonic()
        LOGGER.info("Investigation %s started: %s", investigation_id, request.operation)
        result_queue: Queue[tuple[dict[str, Any] | None, Exception | None]] = Queue(1)

        def run() -> None:
            try:
                result_queue.put((handler(), None))
            except Exception as exception:  # The caller serializes the bounded error.
                result_queue.put((None, exception))

        Thread(
            target=run,
            name=f"tsunade-{request.operation}",
            daemon=True,
        ).start()
        try:
            result, exception = result_queue.get(timeout=request.timeout_seconds)
        except Empty:
            result, exception = {}, None
            status: Literal["OK", "KO", "TIMEOUT"] = "TIMEOUT"
            error = "Investigation exceeded its declared timeout"
        else:
            status = "KO" if exception is not None else "OK"
            error = str(exception)[:1000] if exception is not None else None
            result = result or {}
        if status == "KO":
            LOGGER.error("Investigation %s failed: %s", investigation_id, error)
        duration = monotonic() - started
        finished_at = datetime.now(UTC)
        LOGGER.info("Investigation %s finished with %s", investigation_id, status)
        return InvestigationResult(
            investigation_id=investigation_id,
            operation=request.operation,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
            result=result,
            error=error,
        )

    def _test(self, plugin_id: str) -> dict[str, Any]:
        return self.plugins.test(plugin_id).model_dump(mode="json")

    def _backup_status(self) -> dict[str, Any]:
        state = self.plugins.read("backup")
        result: dict[str, Any] = {
            "status": state.status,
            "enabled": state.enabled,
            "last_execution_at": state.last_execution_at,
            "last_error": state.last_error,
        }
        latest = self.jobs.latest("backup.infra") if self.jobs is not None else None
        if latest is not None:
            result["latest_distributed_job"] = latest.model_dump(mode="json")
            result["status"] = latest.status.value
            if latest.error is not None:
                result["last_error"] = latest.error.message
        return result

    def _host(self, section: str) -> dict[str, Any]:
        snapshot = self.host_health_reader()
        fields = {
            "memory": (
                "memory_percent",
                "memory_total_bytes",
                "memory_available_bytes",
                "swap_percent",
                "swap_total_bytes",
                "swap_used_bytes",
            ),
            "cpu": ("cpu_count", "cpu_percent", "load_1m_per_cpu", "temperature_c"),
            "disk": ("disk_percent", "disk_free_bytes"),
            "services": (
                "failed_systemd_units",
                "inactive_systemd_units",
                "agent_restarts",
            ),
        }[section]
        return {field: snapshot.get(field) for field in fields}
