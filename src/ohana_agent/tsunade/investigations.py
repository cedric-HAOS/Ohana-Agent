"""Finite, authenticated and structured Tsunade investigation operations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.contracts.administration import AdministrationModel
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.plugins.administration import PluginAdministrationRepository
from ohana_agent.tsunade.evidence_privacy import redact_sensitive_value
from ohana_agent.tsunade.local_time import paris_now
from ohana_agent.tsunade.read_only import diagnostic_snapshot

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
        infrastructure_reader: Callable[[], InfrastructureConfig] | None = None,
        configuration_reader: Callable[[str], dict[str, Any]] | None = None,
        http_target_reader: Callable[[str], tuple[str, str] | None] | None = None,
    ) -> None:
        self.plugins = plugins
        self.host_health_reader = host_health_reader
        self.jobs = jobs
        self.infrastructure_reader = infrastructure_reader
        self.configuration_reader = configuration_reader
        self.http_target_reader = http_target_reader
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
            "ntp.status": (
                "Test configured NTP time query",
                15,
                lambda: self._test("ntp"),
            ),
            "dhcp.status": (
                "Test configured local dnsmasq DHCP service",
                15,
                lambda: self._test("dhcp"),
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

    def read_only_snapshot(self, node_id: str) -> dict[str, Any]:
        if self.infrastructure_reader is None:
            return {"status": "unavailable", "reason": "Architecture indisponible"}
        return diagnostic_snapshot(
            self.infrastructure_reader(),
            node_id,
            self.host_health_reader,
            context_reader=(lambda: self.configuration_reader(node_id))
            if self.configuration_reader
            else None,
            configured_http_target=self.http_target_reader(node_id)
            if self.http_target_reader
            else None,
        )

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
        started_at = paris_now()
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
            # Provider exceptions can embed authenticated URLs or response bodies.
            # Keep a useful error class, never their raw text in logs or evidence.
            error = type(exception).__name__ if exception is not None else None
            result = result or {}

        result = redact_sensitive_value(result)

        if status == "KO":
            LOGGER.error("Investigation %s failed: %s", investigation_id, error)
        duration = monotonic() - started
        finished_at = paris_now()
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


def probe_failed(result: InvestigationResult) -> bool:
    """Return whether a completed investigation measured a failing target."""
    # Execution failure supplies no measurement of the target. A completed
    # plugin check can still report success=False and confirm a failed probe.
    if result.status != "OK":
        return False
    data = result.result
    if data.get("success") is False:
        return True
    status = str(data.get("status", "")).casefold()
    if status in {"ko", "error", "failed", "unhealthy", "degraded", "offline"}:
        return True
    if result.operation == "memory.status":
        return (
            float(data.get("memory_percent") or 0) >= 90
            or float(data.get("swap_percent") or 0) >= 75
        )
    if result.operation == "cpu.status":
        return (
            float(data.get("cpu_percent") or 0) >= 95
            or float(data.get("temperature_c") or 0) >= 80
        )
    if result.operation == "disk.usage":
        return float(data.get("disk_percent") or 0) >= 90
    if result.operation == "service.status":
        return bool(
            data.get("failed_systemd_units") or data.get("inactive_systemd_units")
        )
    return False


def investigation_summary(result: InvestigationResult) -> str:
    """Describe both the execution and, when measured, the probe outcome."""
    # "OK" only means the operation ran; a failed MQTT round trip is still OK.
    if result.status == "TIMEOUT":
        return f"{result.operation} : délai dépassé, aucun résultat de sonde"
    if result.status == "KO":
        return f"{result.operation} : exécution en échec, aucun résultat de sonde"
    if probe_failed(result):
        return f"{result.operation} : exécutée, résultat en échec"
    return f"{result.operation} : exécutée, résultat sain"
