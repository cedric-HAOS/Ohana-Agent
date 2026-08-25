"""Authenticated loopback HTTP API for Agent administration."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import ssl
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from threading import Thread
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from administration.companions import (
    CompanionConflictError,
    CompanionRepository,
)
from administration.dhcp import (
    DHCPConfigurationError,
    DnsmasqDHCPRepository,
)
from administration.expertise import (
    TsunadeExpertiseConflictError,
    TsunadeExpertiseService,
)
from administration.incidents import TsunadeIncidentRepository
from administration.infrastructure import (
    InfrastructureConfigurationRepository,
)
from administration.investigations import InvestigationExecutor, InvestigationRequest
from administration.jobs import (
    DistributedJobConflictError,
    DistributedJobRepository,
)
from administration.log_sources import LogSourceBroker
from administration.models import (
    AdministrationCapabilities,
    DHCPConfiguration,
    LogsInvestigationAuthorization,
)
from administration.network import (
    NetworkAdministrationError,
    NetworkManagerRepository,
)
from administration.plugins import PluginAdministrationRepository
from configuration.infrastructure import InfrastructureConfig
from plugins.backup.backup_coordinator import BackupExecutionError

LOGGER = logging.getLogger(__name__)
MAXIMUM_REQUEST_BYTES = 1024 * 1024


class _BoundedRequestStream:
    """Expose exactly one declared HTTP request body and then return EOF."""

    def __init__(self, stream: object, size_bytes: int) -> None:
        self.stream = stream
        self.remaining = size_bytes

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        requested = self.remaining if size < 0 else min(size, self.remaining)
        chunk = self.stream.read(requested)
        self.remaining -= len(chunk)
        return chunk


class AdministrationService:
    """Execute versioned administration operations owned by Agent."""

    def __init__(
        self,
        *,
        infrastructure_repository: InfrastructureConfigurationRepository,
        dhcp_repository: DnsmasqDHCPRepository | None = None,
        plugin_repository: PluginAdministrationRepository | None = None,
        network_repository: NetworkManagerRepository | None = None,
        job_repository: DistributedJobRepository | None = None,
        on_infrastructure_changed: (
            Callable[[InfrastructureConfig], None] | None
        ) = None,
        agent_version: str | None = None,
        worker_ca_certificate_pem: str | None = None,
        worker_ca_sha256: str | None = None,
        wake_timeout_seconds: int = 180,
        wake_sender: Callable[[str], None] | None = None,
        backup_transfer: Any | None = None,
        incident_repository: TsunadeIncidentRepository | None = None,
        investigation_executor: InvestigationExecutor | None = None,
        log_source_broker: LogSourceBroker | None = None,
        expertise_service: TsunadeExpertiseService | None = None,
        log_sources: tuple[str, ...] = (),
        log_window_hours: int = 24,
        log_max_bytes: int = 2 * 1024 * 1024,
        log_timeout_seconds: int = 900,
        companion_repository: CompanionRepository | None = None,
        companion_ca_sha256: str | None = None,
        companion_ca_certificate_pem: str | None = None,
        notification_publisher: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.infrastructure_repository = infrastructure_repository
        self.dhcp_repository = dhcp_repository
        self.plugin_repository = plugin_repository
        self.network_repository = network_repository
        self.job_repository = job_repository
        self.on_infrastructure_changed = on_infrastructure_changed
        self.agent_version = agent_version or self._installed_agent_version()
        if (worker_ca_certificate_pem is None) != (worker_ca_sha256 is None):
            raise ValueError(
                "Worker CA certificate and fingerprint must be configured together"
            )
        self.worker_ca_certificate_pem = worker_ca_certificate_pem
        self.worker_ca_sha256 = worker_ca_sha256
        self.wake_timeout_seconds = wake_timeout_seconds
        self.wake_sender = wake_sender
        self.backup_transfer = backup_transfer
        self.incident_repository = incident_repository
        self.investigation_executor = investigation_executor
        self.log_source_broker = log_source_broker
        self.expertise_service = expertise_service
        self.log_sources = tuple(log_sources)
        self.log_window_hours = log_window_hours
        self.log_max_bytes = log_max_bytes
        self.log_timeout_seconds = log_timeout_seconds
        self.companion_repository = companion_repository
        self.companion_ca_sha256 = companion_ca_sha256
        self.companion_ca_certificate_pem = companion_ca_certificate_pem
        if (companion_ca_sha256 is None) != (companion_ca_certificate_pem is None):
            raise ValueError(
                "Companion CA certificate and fingerprint must be configured together"
            )
        self.notification_publisher = notification_publisher

    def capabilities(self) -> AdministrationCapabilities:
        """Declare the operations actually supported by this Agent."""
        operations = [
            "infrastructure.read",
            "infrastructure.write",
        ]

        if self.dhcp_repository is not None:
            operations.extend(
                [
                    "dhcp.read",
                    "dhcp.write",
                    "dhcp.leases.read",
                ]
            )

        if self.network_repository is not None:
            operations.extend(
                [
                    "system.network.read",
                    "system.network.write",
                    "system.network.confirm",
                    "system.network.rollback",
                ]
            )

        if self.plugin_repository is not None:
            operations.extend(
                [
                    "plugins.read",
                    "plugins.write",
                    "plugins.test",
                    "plugins.backup.icloud.connect",
                    "plugins.backup.run",
                ]
            )

        if self.job_repository is not None:
            operations.extend(
                [
                    "jobs.create",
                    "jobs.read",
                    "jobs.cancel",
                    "jobs.workers.read",
                    "jobs.workers.pairings.read",
                    "jobs.workers.pairings.approve",
                    "jobs.workers.pairings.reject",
                    "jobs.worker.pair",
                    "jobs.worker.register",
                    "jobs.worker.claim",
                    "jobs.worker.heartbeat",
                    "jobs.worker.complete",
                ]
            )

        if self.incident_repository is not None:
            operations.extend(
                [
                    "incidents.read",
                    "incidents.records.write",
                    "incidents.experiences.confirm",
                ]
            )
            if self.dhcp_repository is not None:
                operations.extend(
                    ["incidents.repairs.propose", "incidents.repairs.authorize"]
                )
            operations.extend(
                [
                    "incidents.summary.read",
                    "incidents.requests.read",
                    "incidents.requests.respond",
                    "incidents.activity.read",
                ]
            )
        if self.companion_repository is not None:
            operations.extend(
                [
                    "companions.pairings.read",
                    "companions.pairings.approve",
                    "companions.pairings.reject",
                    "companions.devices.read",
                    "companions.devices.revoke",
                ]
            )
        if self.expertise_service is not None:
            operations.append("incidents.diagnose")
        if self.job_repository is not None and self.log_sources:
            operations.extend(["incidents.logs.check", "incidents.logs.investigate"])
        if self.investigation_executor is not None:
            operations.extend(["investigations.read", "investigations.execute"])

        return AdministrationCapabilities(
            agent_version=self.agent_version,
            operations=operations,
        )

    @staticmethod
    def _installed_agent_version() -> str:
        """Return the installed Ohana-Agent package version."""
        try:
            return package_version("ohana-agent")
        except PackageNotFoundError:
            return "unknown"

    def read_infrastructure(self) -> InfrastructureConfig:
        """Read the Agent-owned infrastructure definition."""
        return self.infrastructure_repository.read()

    def write_infrastructure(
        self,
        payload: dict[str, Any],
    ) -> InfrastructureConfig:
        """Validate, persist and publish an infrastructure definition."""
        configuration = InfrastructureConfig.model_validate(payload)
        saved_configuration = self.infrastructure_repository.write(configuration)

        if self.on_infrastructure_changed is not None:
            self.on_infrastructure_changed(saved_configuration)

        return saved_configuration

    def read_dhcp(self) -> object:
        """Return the DHCP configuration and active leases."""
        if self.dhcp_repository is None:
            raise LookupError("DHCP administration is unavailable")

        return self.dhcp_repository.read()

    def write_dhcp(
        self,
        payload: dict[str, Any],
    ) -> object:
        """Validate and persist the DHCP configuration."""
        if self.dhcp_repository is None:
            raise LookupError("DHCP administration is unavailable")

        configuration = DHCPConfiguration.model_validate(payload)
        return self.dhcp_repository.write(configuration)

    def read_network(self) -> object:
        """Return the active NetworkManager configuration of the Agent host."""
        if self.network_repository is None:
            raise LookupError("Agent network administration is unavailable")
        return self.network_repository.read()

    def write_network(self, payload: dict[str, Any]) -> object:
        """Apply a candidate host network configuration with rollback protection."""
        if self.network_repository is None:
            raise LookupError("Agent network administration is unavailable")
        return self.network_repository.apply(payload)

    def confirm_network(self, transaction_id: str) -> object:
        """Confirm a pending host network configuration."""
        if self.network_repository is None:
            raise LookupError("Agent network administration is unavailable")
        return self.network_repository.confirm(transaction_id)

    def rollback_network(self, transaction_id: str) -> object:
        """Restore the previous host network configuration immediately."""
        if self.network_repository is None:
            raise LookupError("Agent network administration is unavailable")
        return self.network_repository.rollback(transaction_id)

    def list_plugins(self) -> object:
        """Return all registered and administrable plugins."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")

        return self.plugin_repository.list()

    def read_plugin(self, identifier: str) -> object:
        """Return one plugin configuration and runtime state."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")

        return self.plugin_repository.read(identifier)

    def write_plugin(
        self,
        identifier: str,
        payload: dict[str, Any],
    ) -> object:
        """Persist and immediately apply one plugin configuration."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")

        return self.plugin_repository.write(identifier, payload)

    def test_plugin(self, identifier: str) -> object:
        """Execute one immediate plugin capability check."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")

        return self.plugin_repository.test(identifier)

    def connect_backup_icloud(self, payload: dict[str, Any]) -> object:
        """Start or complete the iCloud authentication flow."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")
        return self.plugin_repository.connect_backup_icloud(payload)

    def run_backup(self, target_id: str) -> object:
        """Start one configured HAOS backup in the background."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")
        return self.plugin_repository.run_backup(target_id)

    def list_incidents(self, state: str = "active") -> object:
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        summary = self.incident_repository.statistics()
        latest_log_health = None
        if self.job_repository is not None:
            summary["log_control_count"] = self.job_repository.count(
                "logs.health_check"
            )
            latest = self.job_repository.latest_for_incident("logs.health_check", None)
            if latest is not None:
                latest_log_health = {
                    "job_id": str(latest.job_id),
                    "status": latest.status.value,
                    "created_at": latest.created_at.isoformat(),
                    "finished_at": latest.finished_at.isoformat()
                    if latest.finished_at
                    else None,
                    "result": latest.result,
                    "error": latest.error.model_dump(mode="json")
                    if latest.error
                    else None,
                }
        else:
            summary["log_control_count"] = 0
        return {
            "schema_version": 1,
            "state": state,
            "summary": summary,
            "log_health": latest_log_health,
            "incidents": [
                incident.model_dump(mode="json")
                for incident in self.incident_repository.list(state=state)
            ],
        }

    def read_incident(self, incident_id: str) -> object:
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        return self.incident_repository.get(incident_id)

    def read_companion_summary(self) -> object:
        """Return the smallest useful Konoha overview for a personal companion."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        incidents = self.incident_repository.list(state="active", limit=20)
        requests = self.incident_repository.list_user_requests(state="pending").requests
        severity = (
            "critical"
            if any(incident.severity == "critical" for incident in incidents)
            else "degraded"
            if incidents
            else "healthy"
        )
        last_checked_at = max(
            (incident.last_observed_at for incident in incidents),
            default=None,
        )
        latest_log_health = None
        if self.job_repository is not None:
            latest_log_health = self.job_repository.latest_for_incident(
                "logs.health_check", None
            )
            if latest_log_health is not None:
                candidate = (
                    latest_log_health.finished_at or latest_log_health.created_at
                )
                if last_checked_at is None or candidate > last_checked_at:
                    last_checked_at = candidate
        pending_count = len(requests)
        message = (
            "Aucune intervention requise"
            if pending_count == 0
            else f"{pending_count} décision(s) attendent votre réponse"
        )
        attention = [
            {
                "incident_id": str(incident.incident_id),
                "equipment": incident.equipment_id,
                "capability": incident.capability_id,
                "severity": incident.severity,
                "message": incident.message,
                "started_at": incident.started_at.isoformat(),
            }
            for incident in incidents[:5]
        ]
        return {
            "schema_version": 1,
            "konoha_state": severity,
            "tsunade_message": message,
            "pending_requests": pending_count,
            "last_checked_at": last_checked_at.isoformat() if last_checked_at else None,
            "attention": attention,
        }

    def read_companion_requests(self, state: str = "pending") -> object:
        """Expose structured Tsunade questions without technical incident payloads."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        return self.incident_repository.list_user_requests(
            state="all" if state == "all" else "pending"
        )

    def read_companion_activity(self) -> object:
        """Return a bounded human timeline, not Vision's technical history."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        activity = [
            item.model_dump(mode="json")
            for item in self.incident_repository.companion_activity(limit=20)
        ]
        if self.job_repository is not None:
            latest = self.job_repository.latest_for_incident("logs.health_check", None)
            if latest is not None and latest.finished_at is not None:
                activity.append(
                    {
                        "activity_id": f"log-control-{latest.job_id}",
                        "occurred_at": latest.finished_at.isoformat(),
                        "kind": "investigation",
                        "title": "Contrôle quotidien des journaux terminé",
                        "detail": "Konoha : OK"
                        if latest.status.value == "SUCCEEDED"
                        else "Le contrôle nécessite une attention.",
                        "incident_id": None,
                    }
                )
        activity.sort(key=lambda item: str(item["occurred_at"]), reverse=True)
        return {"schema_version": 1, "activity": activity[:20]}

    def respond_companion_request(
        self,
        request_id: str,
        device_id: str,
        payload: dict[str, Any],
    ) -> object:
        """Route a structured answer through Tsunade and Agent's existing executor."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        choice = str(payload.get("choice") or "").upper()
        request = self.incident_repository.get_user_request(request_id)
        response = {
            "choice": choice,
            "source": "shizune",
            "answered_by": device_id,
        }
        if choice == "LATER":
            return self.incident_repository.defer_user_request(request_id, response)
        if request.kind != "repair_authorization":
            return self.incident_repository.answer_user_request(request_id, response)
        repair_id = self.incident_repository.user_request_action_reference(request_id)
        if repair_id is None:
            raise ValueError("La demande ne référence aucune action autorisée")
        if choice == "AUTHORIZE":
            self.authorize_incident_repair(
                str(request.incident_id),
                {
                    "repair_id": repair_id,
                    "source": "shizune",
                    "authorized_by": device_id,
                },
            )
        elif choice == "REFUSE":
            self.incident_repository.refuse_repair(
                request.incident_id,
                repair_id,
                source="shizune",
                answered_by=device_id,
            )
        else:
            raise ValueError("Cette réponse n’est pas valable pour la réparation")
        return self.incident_repository.get_user_request(request_id)

    def create_companion_pairing(self, payload: dict[str, Any]) -> object:
        if (
            self.companion_repository is None
            or self.companion_ca_sha256 is None
            or self.companion_ca_certificate_pem is None
        ):
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.create_pairing(
            payload,
            tls_ca_sha256=self.companion_ca_sha256,
            tls_ca_certificate_pem=self.companion_ca_certificate_pem,
        )

    def poll_companion_pairing(
        self, pairing_id: str, payload: dict[str, Any]
    ) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.poll_pairing(pairing_id, payload)

    def list_companion_pairings(self) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.list_pairings()

    def approve_companion_pairing(self, pairing_id: str) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.approve_pairing(pairing_id)

    def reject_companion_pairing(self, pairing_id: str) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.reject_pairing(pairing_id)

    def list_companion_devices(self) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.list_devices()

    def revoke_companion_device(self, device_id: str) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.revoke(device_id)

    def register_companion_notifications(
        self, device_id: str, payload: dict[str, Any]
    ) -> object:
        """Bind APNs delivery only to the authenticated companion session."""
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.register_push_token(device_id, payload)

    def append_incident_record(
        self, incident_id: str, payload: dict[str, Any]
    ) -> object:
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        return self.incident_repository.append_record(incident_id, payload)

    def diagnose_incident(self, incident_id: str) -> object:
        """Run Tsunade's bounded deterministic-first expertise cycle."""
        if self.expertise_service is None:
            raise LookupError("Tsunade expertise is unavailable")
        return self.expertise_service.diagnose(incident_id)

    def propose_incident_repair(
        self, incident_id: str, payload: dict[str, Any]
    ) -> object:
        if self.incident_repository is None or self.dhcp_repository is None:
            raise LookupError("Les réparations supervisées sont indisponibles")
        repair = self.incident_repository.propose_repair(incident_id, payload)
        self._publish_notification(
            {
                "schema_version": 1,
                "notification_id": f"repair-{repair.repair_id}-decision",
                "type": "DECISION_REQUIRED",
                "title": "Tsunade a besoin de votre décision",
                "message": "Une réparation supervisée attend votre autorisation.",
                "incident_id": str(repair.incident_id),
                "occurred_at": repair.proposed_at.isoformat(),
            }
        )
        return repair

    def authorize_incident_repair(
        self, incident_id: str, payload: dict[str, Any]
    ) -> object:
        """Audit authorization, invoke one concrete helper, then await Shikamaru."""
        if self.incident_repository is None or self.dhcp_repository is None:
            raise LookupError("Les réparations supervisées sont indisponibles")
        repair = self.incident_repository.authorize_repair(incident_id, payload)
        try:
            self.dhcp_repository.request_supervised_restart()
        except Exception as error:
            result = self.incident_repository.mark_repair_execution_failed(
                repair.repair_id, error
            )
            self._publish_notification(
                {
                    "schema_version": 1,
                    "notification_id": f"repair-{repair.repair_id}-failed",
                    "type": "ATTENTION",
                    "title": "La réparation a échoué",
                    "message": result.result or "Tsunade n’a pas pu exécuter l’action.",
                    "incident_id": str(repair.incident_id),
                    "occurred_at": datetime.now(UTC).isoformat(),
                }
            )
            return result
        return self.incident_repository.mark_repair_executed(repair.repair_id)

    def _publish_notification(self, payload: dict[str, Any]) -> None:
        """Keep notifications strictly optional for Agent and Tsunade."""
        if self.notification_publisher is None:
            return
        try:
            self.notification_publisher(payload)
        except Exception:
            LOGGER.warning(
                "Unable to publish an optional Tsunade notification", exc_info=True
            )

    def confirm_incident_experience(
        self, incident_id: str, payload: dict[str, Any]
    ) -> object:
        if self.incident_repository is None:
            raise LookupError("La mémoire des diagnostics est indisponible")
        return self.incident_repository.confirm_experience(incident_id, payload)

    def request_log_health_check(
        self,
        *,
        now: datetime | None = None,
        sources: list[str] | tuple[str, ...] | None = None,
        window_hours: int | None = None,
        max_bytes: int | None = None,
        timeout_seconds: int | None = None,
    ) -> object:
        """Ask Katsuyu for one bounded deterministic control chosen by Tsunade."""
        if self.job_repository is None or not self.log_sources:
            raise LookupError("Tsunade log analysis is unavailable")
        selected_sources = list(sources or self.log_sources)
        if not selected_sources or any(
            source not in self.log_sources for source in selected_sources
        ):
            raise ValueError("log source is not enabled by Tsunade")
        active = self.job_repository.active_for_incident("logs.health_check", None)
        if active is not None:
            raise DistributedJobConflictError(
                f"log health check is already active as job {active.job_id}"
            )
        current = (now or datetime.now(UTC)).astimezone(UTC)
        selected_window = window_hours or self.log_window_hours
        baseline: list[dict[str, object]] = []
        previous = self.job_repository.latest_successful_result("logs.health_check")
        for source in (previous or {}).get("sources", []):
            if not isinstance(source, dict):
                continue
            for finding in source.get("findings", []):
                if isinstance(finding, dict) and len(baseline) < 192:
                    baseline.append(
                        {
                            "source": source.get("source"),
                            "signature": finding.get("signature"),
                            "occurrences": finding.get("occurrences"),
                        }
                    )
        return self.create_job(
            {
                "protocol_version": 1,
                "job_id": str(uuid4()),
                "type": "logs.health_check",
                "created_at": current.isoformat(),
                "parameters": {
                    "sources": selected_sources,
                    "window_started_at": (
                        current - timedelta(hours=selected_window)
                    ).isoformat(),
                    "window_ended_at": current.isoformat(),
                    "max_bytes_per_source": max_bytes or self.log_max_bytes,
                    "baseline": baseline,
                    "incident_id": None,
                },
                "timeout": timeout_seconds or self.log_timeout_seconds,
            }
        )

    def request_log_investigation(
        self, incident_id: str, payload: dict[str, Any]
    ) -> object:
        """Queue an operator-authorized follow-up for one log incident."""
        if self.job_repository is None or not self.log_sources:
            raise LookupError("Tsunade log analysis is unavailable")
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        authorization = LogsInvestigationAuthorization.model_validate(payload)
        incident = self.incident_repository.get(incident_id)
        if incident.state != "active" or incident.capability_id != "logs.health":
            raise ValueError(
                "log investigation requires an active logs.health incident"
            )
        if incident.node_id not in self.log_sources:
            raise ValueError("incident log source is not enabled by Tsunade")
        active = self.job_repository.active_for_incident(
            "logs.investigate", str(incident.incident_id)
        )
        if active is not None:
            raise DistributedJobConflictError(
                f"log investigation is already active as job {active.job_id}"
            )
        current = datetime.now(UTC)
        job = self.create_job(
            {
                "protocol_version": 1,
                "job_id": str(uuid4()),
                "type": "logs.investigate",
                "created_at": current.isoformat(),
                "parameters": {
                    "source": incident.node_id,
                    "window_started_at": (current - timedelta(hours=2)).isoformat(),
                    "window_ended_at": current.isoformat(),
                    "pattern": authorization.pattern,
                    "max_bytes": self.log_max_bytes,
                    "incident_id": str(incident.incident_id),
                },
                "timeout": self.log_timeout_seconds,
            }
        )
        self.incident_repository.append_record(
            incident.incident_id,
            {
                "kind": "investigation",
                "summary": "Analyse approfondie des journaux autorisée",
                "payload": {
                    "job_id": str(job.job_id),
                    "source": incident.node_id,
                    "pattern": authorization.pattern,
                },
            },
        )
        return job

    def list_investigations(self) -> object:
        if self.investigation_executor is None:
            raise LookupError("Tsunade investigations are unavailable")
        return {
            "schema_version": 1,
            "operations": [
                operation.model_dump(mode="json")
                for operation in self.investigation_executor.catalog()
            ],
        }

    def execute_investigation(self, payload: dict[str, Any]) -> object:
        if self.investigation_executor is None:
            raise LookupError("Tsunade investigations are unavailable")
        request = InvestigationRequest.model_validate(payload)
        result = self.investigation_executor.execute(payload)
        if request.incident_id is not None:
            if self.incident_repository is None:
                raise LookupError("Tsunade incidents are unavailable")
            self.incident_repository.append_record(
                request.incident_id,
                {
                    "kind": "investigation",
                    "summary": f"{result.operation}: {result.status}",
                    "payload": result.model_dump(mode="json"),
                },
            )
        return result

    def create_job(self, payload: dict[str, Any]) -> object:
        """Validate and queue one explicitly typed distributed job."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        job = self.job_repository.create(payload)
        self._wake_compatible_worker(job.type)
        return job

    def _wake_compatible_worker(self, job_type: str) -> None:
        """Wake one unavailable compatible worker using its advertised WOL MAC."""
        if self.job_repository is None or self.wake_sender is None:
            return
        worker = self.job_repository.wake_candidate(job_type)
        if worker is None or worker.wake_on_lan_mac_address is None:
            return
        try:
            self.wake_sender(worker.wake_on_lan_mac_address)
            self.job_repository.mark_worker_waking(
                worker.worker_id,
                timeout_seconds=self.wake_timeout_seconds,
            )
        except (OSError, ValueError):
            LOGGER.exception(
                "Unable to send Wake-on-LAN for Katsuyu worker %s",
                worker.worker_id,
            )

    def read_job(self, job_id: str) -> object:
        """Read the current durable state of one job."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.get(job_id)

    def cancel_job(self, job_id: str) -> object:
        """Cancel one job through the Tsunade control plane."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.cancel(job_id)

    def claim_job(self, payload: dict[str, Any]) -> object:
        """Lease the oldest compatible job to Katsuyu."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.claim(payload)

    def register_worker(
        self,
        payload: dict[str, Any],
        *,
        previous_worker_id: str | None = None,
    ) -> object:
        """Register Katsuyu and its finite capabilities."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.register_worker(
            payload,
            previous_worker_id=previous_worker_id,
        )

    def list_workers(self) -> object:
        """List the worker registrations visible to Tsunade."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.list_workers()

    def create_worker_pairing(self, payload: dict[str, Any]) -> object:
        """Open a bounded Katsuyu pairing request for later approval."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        pairing = self.job_repository.create_pairing(payload)
        return pairing.model_copy(update={"tls_ca_sha256": self.worker_ca_sha256})

    def list_worker_pairings(self) -> object:
        """List pairing requests visible to the administration plane."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        collection = self.job_repository.list_pairings()
        return collection.model_copy(
            update={
                "pairings": [
                    pairing.model_copy(update={"tls_ca_sha256": self.worker_ca_sha256})
                    for pairing in collection.pairings
                ]
            }
        )

    def read_worker_trust(self) -> object:
        """Return the public CA material used by the dedicated worker listener."""
        if self.worker_ca_certificate_pem is None or self.worker_ca_sha256 is None:
            raise LookupError("Katsuyu HTTPS trust is unavailable")
        return {
            "schema_version": 1,
            "ca_certificate_pem": self.worker_ca_certificate_pem,
            "ca_sha256": self.worker_ca_sha256,
        }

    def approve_worker_pairing(self, pairing_id: str) -> object:
        """Approve one verification code checked by the administrator."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.approve_pairing(pairing_id)

    def reject_worker_pairing(self, pairing_id: str) -> object:
        """Reject one untrusted or obsolete pairing request."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.reject_pairing(pairing_id)

    def poll_worker_pairing(self, pairing_id: str, payload: dict[str, Any]) -> object:
        """Let the originating installer retrieve its credential once."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.poll_pairing(pairing_id, payload)

    def heartbeat_job(self, job_id: str, payload: dict[str, Any]) -> object:
        """Renew a job lease for its current Katsuyu attempt."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.heartbeat(job_id, payload)

    def complete_job(self, job_id: str, payload: dict[str, Any]) -> object:
        """Record a verified result from the current Katsuyu attempt."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        job = self.job_repository.complete(job_id, payload)
        if (
            job.status.value == "SUCCEEDED"
            and job.result is not None
            and self.incident_repository is not None
        ):
            incident_id = job.parameters.get("incident_id")
            if job.type == "logs.health_check":
                self.incident_repository.record_log_health(
                    job.job_id,
                    job.result,
                    incident_id=incident_id,
                )
                if incident_id is not None and self.expertise_service is not None:
                    self.expertise_service.start(
                        incident_id,
                        log_result=job.result,
                    )
            elif job.type == "logs.investigate" and incident_id is not None:
                self.incident_repository.record_log_investigation(
                    job.job_id,
                    incident_id,
                    job.result,
                )
            elif job.type == "ai.inference" and incident_id is not None:
                if self.expertise_service is not None:
                    self.expertise_service.record_ai_result(
                        incident_id,
                        job.job_id,
                        job.result,
                    )
        elif (
            job.type == "ai.inference"
            and job.parameters.get("incident_id") is not None
            and self.expertise_service is not None
            and job.status.value == "FAILED"
        ):
            self.expertise_service.record_ai_failure(
                job.parameters["incident_id"],
                job.job_id,
                job.error.message if job.error is not None else "unknown failure",
            )
        return job

    def authorize_backup_transfer(
        self, job_id: str, worker_id: str, attempt: int
    ) -> object:
        if self.backup_transfer is None:
            raise LookupError("Distributed INFRA backup transfer is unavailable")
        return self.backup_transfer.authorize(job_id, worker_id, attempt)

    def open_backup_source(self, job_id: str, worker_id: str, attempt: int) -> object:
        if self.backup_transfer is None:
            raise LookupError("Distributed INFRA backup transfer is unavailable")
        return self.backup_transfer.open_source(job_id, worker_id, attempt)

    def receive_backup_artifact(
        self,
        job_id: str,
        worker_id: str,
        attempt: int,
        stream: object,
        size_bytes: int,
        sha256: str,
    ) -> object:
        if self.backup_transfer is None:
            raise LookupError("Distributed INFRA backup transfer is unavailable")
        return self.backup_transfer.receive_artifact(
            job_id,
            worker_id,
            attempt,
            stream,
            size_bytes=size_bytes,
            expected_sha256=sha256,
        )

    def read_log_source(
        self,
        job_id: str,
        worker_id: str,
        attempt: int,
        source_id: str,
    ) -> object:
        """Return one short-lived job-bound descriptor, never raw journals."""
        if self.log_source_broker is None:
            raise LookupError("Distributed log sources are unavailable")
        return self.log_source_broker.descriptor(job_id, worker_id, attempt, source_id)


class AdministrationHTTPServer:
    """Run the administration API in a dedicated loopback thread."""

    def __init__(
        self,
        *,
        service: AdministrationService,
        token: str,
        worker_token: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
        worker_only: bool = False,
        companion_only: bool = False,
        tls_certificate_file: Path | None = None,
        tls_private_key_file: Path | None = None,
    ) -> None:
        normalized_token = token.strip()

        if not normalized_token:
            raise ValueError("Administration token cannot be empty.")

        self.service = service
        self.token = normalized_token
        self.worker_token = worker_token.strip() if worker_token else None
        if self.worker_token and hmac.compare_digest(self.worker_token, self.token):
            raise ValueError("Worker and administration tokens must be different.")
        self.host = host
        self.port = port
        if worker_only and companion_only:
            raise ValueError("A listener cannot be worker-only and companion-only")
        if (tls_certificate_file is None) != (tls_private_key_file is None):
            raise ValueError(
                "TLS certificate and private key must be configured together"
            )
        self.worker_only = worker_only
        self.companion_only = companion_only
        self.tls_certificate_file = tls_certificate_file
        self.tls_private_key_file = tls_private_key_file
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def running(self) -> bool:
        """Return whether the administration server thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def address(self) -> tuple[str, int] | None:
        """Return the effective listening address."""
        if self._server is None:
            return None

        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        """Start the HTTP server once."""
        if self.running:
            return

        handler_class = self._handler_class()
        server = ThreadingHTTPServer(
            (self.host, self.port),
            handler_class,
        )
        if self.tls_certificate_file is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            try:
                context.load_cert_chain(
                    certfile=self.tls_certificate_file,
                    keyfile=self.tls_private_key_file,
                )
                server.socket = context.wrap_socket(server.socket, server_side=True)
            except Exception:
                server.server_close()
                raise
        self._server = server
        self._thread = Thread(
            target=self._server.serve_forever,
            name=(
                "ohana-agent-worker-https"
                if self.worker_only
                else "ohana-agent-companion-https"
                if self.companion_only
                else "ohana-agent-administration"
            ),
            daemon=True,
        )
        self._thread.start()
        scheme = "https" if self.tls_certificate_file is not None else "http"
        role = (
            "Katsuyu worker API"
            if self.worker_only
            else "Companion API"
            if self.companion_only
            else "Administration API"
        )
        LOGGER.info("%s listening on %s://%s:%s", role, scheme, *self.address)

    def stop(self) -> None:
        """Stop the HTTP server and release its socket."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

        if self._thread is not None:
            self._thread.join(timeout=5)

        self._server = None
        self._thread = None

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        service = self.service
        expected_token = self.token
        expected_worker_token = self.worker_token
        worker_only = self.worker_only
        companion_only = self.companion_only

        class AdministrationRequestHandler(BaseHTTPRequestHandler):
            """Handle one administration request."""

            server_version = "Ohana-Agent-Administration/1"

            def do_GET(self) -> None:  # noqa: N802
                """Handle administration reads."""
                path = self.path.split("?", 1)[0]
                if worker_only:
                    input_suffix = "/input"
                    log_source_marker = "/log-source/"
                    if path.startswith("/v1/jobs/") and path.endswith(input_suffix):
                        job_id = path[len("/v1/jobs/") : -len(input_suffix)]
                        if job_id and "/" not in job_id:
                            self._download_backup_source(job_id)
                        else:
                            self._write_error(
                                HTTPStatus.NOT_FOUND, "Worker endpoint not found"
                            )
                    elif path.startswith("/v1/jobs/") and log_source_marker in path:
                        remainder = path[len("/v1/jobs/") :]
                        job_id, separator, source_id = remainder.partition(
                            log_source_marker
                        )
                        if separator and job_id and source_id and "/" not in source_id:
                            identity = self._worker_transfer_identity()
                            if identity is not None:
                                worker_id, attempt = identity
                                self._execute(
                                    lambda: service.read_log_source(
                                        job_id,
                                        worker_id,
                                        attempt,
                                        source_id,
                                    )
                                )
                        else:
                            self._write_error(
                                HTTPStatus.NOT_FOUND, "Worker endpoint not found"
                            )
                    elif path == "/v1/jobs/workers/trust":
                        self._execute(service.read_worker_trust)
                    else:
                        self._write_error(
                            HTTPStatus.NOT_FOUND,
                            "Worker endpoint not found",
                        )
                    return
                if companion_only:
                    if path == "/v1/pairings/companions/trust":
                        if service.companion_ca_sha256 is None:
                            self._write_error(
                                HTTPStatus.NOT_FOUND,
                                "Companion trust is unavailable",
                            )
                        else:
                            self._write_json(
                                HTTPStatus.OK,
                                {
                                    "schema_version": 1,
                                    "tls_ca_sha256": service.companion_ca_sha256,
                                    "tls_ca_certificate_pem": (
                                        service.companion_ca_certificate_pem
                                    ),
                                },
                            )
                        return
                    identity = self._companion_identity()
                    if identity is None:
                        return
                    routes: dict[str, Callable[[], object]] = {
                        "/v1/incidents/summary": service.read_companion_summary,
                        "/v1/incidents/requests": service.read_companion_requests,
                        "/v1/incidents/requests/all": partial(
                            service.read_companion_requests, "all"
                        ),
                        "/v1/incidents/activity": service.read_companion_activity,
                    }
                    operation = routes.get(path)
                    if operation is None:
                        self._write_error(
                            HTTPStatus.NOT_FOUND, "Companion endpoint not found"
                        )
                    else:
                        self._execute(operation)
                    return
                if not self._authorized(expected_token, "administration"):
                    return

                routes: dict[str, Callable[[], object]] = {
                    "/v1/capabilities": service.capabilities,
                    "/v1/infrastructure": service.read_infrastructure,
                    "/v1/dhcp": service.read_dhcp,
                    "/v1/plugins": service.list_plugins,
                    "/v1/system/network": service.read_network,
                    "/v1/jobs/workers": service.list_workers,
                    "/v1/jobs/workers/pairings": service.list_worker_pairings,
                    "/v1/pairings/companions": service.list_companion_pairings,
                    "/v1/companions": service.list_companion_devices,
                    "/v1/incidents": service.list_incidents,
                    "/v1/incidents/resolved": partial(
                        service.list_incidents, "resolved"
                    ),
                    "/v1/incidents/all": partial(service.list_incidents, "all"),
                    "/v1/investigations": service.list_investigations,
                }
                operation = routes.get(path)

                if operation is None and path.startswith("/v1/plugins/"):
                    identifier = path.removeprefix("/v1/plugins/")

                    if identifier and "/" not in identifier:
                        plugin_identifier = identifier

                        def operation() -> object:
                            return service.read_plugin(plugin_identifier)

                if operation is None and path.startswith("/v1/jobs/"):
                    job_id = path.removeprefix("/v1/jobs/")
                    if job_id and "/" not in job_id:
                        operation = partial(service.read_job, job_id)

                if operation is None and path.startswith("/v1/incidents/"):
                    incident_id = path.removeprefix("/v1/incidents/")
                    if incident_id and "/" not in incident_id:
                        operation = partial(service.read_incident, incident_id)

                if operation is None:
                    self._write_error(
                        HTTPStatus.NOT_FOUND,
                        "Administration endpoint not found",
                    )
                    return

                self._execute(operation)

            def do_PUT(self) -> None:  # noqa: N802
                """Handle configuration changes."""
                if worker_only:
                    self._write_error(HTTPStatus.NOT_FOUND, "Worker endpoint not found")
                    return
                if not self._authorized(expected_token, "administration"):
                    return

                path = self.path.split("?", 1)[0]
                routes: dict[str, Callable[[dict[str, Any]], object]] = {
                    "/v1/infrastructure": service.write_infrastructure,
                    "/v1/dhcp": service.write_dhcp,
                    "/v1/system/network": service.write_network,
                }
                operation = routes.get(path)

                if operation is None and path.startswith("/v1/plugins/"):
                    identifier = path.removeprefix("/v1/plugins/")

                    if identifier and "/" not in identifier:
                        plugin_identifier = identifier

                        def operation(payload: object) -> object:
                            return service.write_plugin(
                                plugin_identifier,
                                payload,
                            )

                if operation is None:
                    self._write_error(
                        HTTPStatus.NOT_FOUND,
                        "Administration endpoint not found",
                    )
                    return

                payload = self._read_json()

                if payload is None:
                    return

                self._execute(
                    lambda: operation(payload),
                )

            def do_POST(self) -> None:  # noqa: N802
                """Handle immediate administration actions."""
                path = self.path.split("?", 1)[0]
                if companion_only:
                    pairing_prefix = "/v1/pairings/companions/"
                    if path == "/v1/pairings/companions":
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.create_companion_pairing(payload)
                            )
                        return
                    if path.startswith(pairing_prefix) and path.endswith("/poll"):
                        pairing_id = path[len(pairing_prefix) : -len("/poll")]
                        if pairing_id and "/" not in pairing_id:
                            payload = self._read_json()
                            if payload is not None:
                                self._execute(
                                    lambda: service.poll_companion_pairing(
                                        pairing_id, payload
                                    )
                                )
                        else:
                            self._write_error(
                                HTTPStatus.NOT_FOUND,
                                "Companion endpoint not found",
                            )
                        return
                    identity = self._companion_identity()
                    if identity is None:
                        return
                    if path == "/v1/companions/notifications":
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.register_companion_notifications(
                                    identity, payload
                                )
                            )
                        return
                    response_prefix = "/v1/incidents/requests/"
                    response_suffix = "/response"
                    if path.startswith(response_prefix) and path.endswith(
                        response_suffix
                    ):
                        request_id = path[len(response_prefix) : -len(response_suffix)]
                        if request_id and "/" not in request_id:
                            payload = self._read_json()
                            if payload is not None:
                                self._execute(
                                    lambda: service.respond_companion_request(
                                        request_id, identity, payload
                                    )
                                )
                            return
                    self._write_error(
                        HTTPStatus.NOT_FOUND, "Companion endpoint not found"
                    )
                    return
                artifact_suffix = "/artifact"
                if path.startswith("/v1/jobs/") and path.endswith(artifact_suffix):
                    job_id = path[len("/v1/jobs/") : -len(artifact_suffix)]
                    if job_id and "/" not in job_id:
                        self._upload_backup_artifact(job_id)
                    else:
                        self._write_error(
                            HTTPStatus.NOT_FOUND, "Worker endpoint not found"
                        )
                    return
                if path == "/v1/jobs/workers/pairings":
                    payload = self._read_json()
                    if payload is not None:
                        self._execute(lambda: service.create_worker_pairing(payload))
                    return

                pairing_prefix = "/v1/jobs/workers/pairings/"
                pairing_poll_suffix = "/poll"
                if path.startswith(pairing_prefix) and path.endswith(
                    pairing_poll_suffix
                ):
                    pairing_id = path[len(pairing_prefix) : -len(pairing_poll_suffix)]
                    if pairing_id and "/" not in pairing_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                partial(
                                    service.poll_worker_pairing,
                                    pairing_id,
                                    payload,
                                )
                            )
                        return

                if path == "/v1/jobs/workers/register":
                    payload = self._read_json()
                    previous_worker_id = (
                        self.headers.get("X-Ohana-Previous-Worker-Id", "").strip()
                        or None
                    )
                    if payload is not None and self._authorized_worker(
                        payload,
                        previous_worker_id=previous_worker_id,
                    ):
                        self._execute(
                            lambda: service.register_worker(
                                payload,
                                previous_worker_id=previous_worker_id,
                            )
                        )
                    return
                if path == "/v1/jobs/claim":
                    payload = self._read_json()
                    if payload is not None and self._authorized_worker(payload):
                        self._execute(lambda: service.claim_job(payload))
                    return

                jobs_prefix = "/v1/jobs/"
                for action, operation in (
                    ("heartbeat", service.heartbeat_job),
                    ("complete", service.complete_job),
                ):
                    action_suffix = f"/{action}"
                    if path.startswith(jobs_prefix) and path.endswith(action_suffix):
                        job_id = path[len(jobs_prefix) : -len(action_suffix)]
                        if job_id and "/" not in job_id:
                            payload = self._read_json()
                            if payload is not None and self._authorized_worker(payload):
                                self._execute(partial(operation, job_id, payload))
                            return

                if worker_only:
                    self._write_error(HTTPStatus.NOT_FOUND, "Worker endpoint not found")
                    return

                if not self._authorized(expected_token, "administration"):
                    return

                companion_pairing_prefix = "/v1/pairings/companions/"
                for action, operation in (
                    ("approve", service.approve_companion_pairing),
                    ("reject", service.reject_companion_pairing),
                ):
                    suffix = f"/{action}"
                    if path.startswith(companion_pairing_prefix) and path.endswith(
                        suffix
                    ):
                        pairing_id = path[len(companion_pairing_prefix) : -len(suffix)]
                        if pairing_id and "/" not in pairing_id:
                            self._execute(partial(operation, pairing_id))
                            return
                companion_prefix = "/v1/companions/"
                revoke_suffix = "/revoke"
                if path.startswith(companion_prefix) and path.endswith(revoke_suffix):
                    device_id = path[len(companion_prefix) : -len(revoke_suffix)]
                    if device_id and "/" not in device_id:
                        self._execute(
                            partial(service.revoke_companion_device, device_id)
                        )
                        return

                if path == "/v1/jobs":
                    payload = self._read_json()
                    if payload is not None:
                        self._execute(lambda: service.create_job(payload))
                    return

                if path == "/v1/investigations":
                    payload = self._read_json()
                    if payload is not None:
                        self._execute(lambda: service.execute_investigation(payload))
                    return

                if path == "/v1/incidents/logs/check":
                    self._execute(service.request_log_health_check)
                    return

                incident_prefix = "/v1/incidents/"
                record_suffix = "/records"
                diagnose_suffix = "/diagnose"
                logs_investigate_suffix = "/logs/investigate"
                repair_authorize_suffix = "/repairs/authorize"
                repairs_suffix = "/repairs"
                experience_suffix = "/experience"
                if path.startswith(incident_prefix) and path.endswith(
                    logs_investigate_suffix
                ):
                    incident_id = path[
                        len(incident_prefix) : -len(logs_investigate_suffix)
                    ]
                    if incident_id and "/" not in incident_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.request_log_investigation(
                                    incident_id, payload
                                )
                            )
                    return
                if path.startswith(incident_prefix) and path.endswith(
                    repair_authorize_suffix
                ):
                    incident_id = path[
                        len(incident_prefix) : -len(repair_authorize_suffix)
                    ]
                    if incident_id and "/" not in incident_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.authorize_incident_repair(
                                    incident_id, payload
                                )
                            )
                    return
                if path.startswith(incident_prefix) and path.endswith(repairs_suffix):
                    incident_id = path[len(incident_prefix) : -len(repairs_suffix)]
                    if incident_id and "/" not in incident_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.propose_incident_repair(
                                    incident_id, payload
                                )
                            )
                    return
                if path.startswith(incident_prefix) and path.endswith(
                    experience_suffix
                ):
                    incident_id = path[len(incident_prefix) : -len(experience_suffix)]
                    if incident_id and "/" not in incident_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.confirm_incident_experience(
                                    incident_id, payload
                                )
                            )
                    return
                if path.startswith(incident_prefix) and path.endswith(diagnose_suffix):
                    incident_id = path[len(incident_prefix) : -len(diagnose_suffix)]
                    if incident_id and "/" not in incident_id:
                        self._execute(partial(service.diagnose_incident, incident_id))
                    return
                if path.startswith(incident_prefix) and path.endswith(record_suffix):
                    incident_id = path[len(incident_prefix) : -len(record_suffix)]
                    if incident_id and "/" not in incident_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.append_incident_record(
                                    incident_id, payload
                                )
                            )
                        return

                for action, operation in (
                    ("approve", service.approve_worker_pairing),
                    ("reject", service.reject_worker_pairing),
                ):
                    suffix = f"/{action}"
                    if path.startswith(pairing_prefix) and path.endswith(suffix):
                        pairing_id = path[len(pairing_prefix) : -len(suffix)]
                        if pairing_id and "/" not in pairing_id:
                            self._execute(partial(operation, pairing_id))
                            return

                cancel_suffix = "/cancel"
                if path.startswith(jobs_prefix) and path.endswith(cancel_suffix):
                    job_id = path[len(jobs_prefix) : -len(cancel_suffix)]
                    if job_id and "/" not in job_id:
                        self._execute(partial(service.cancel_job, job_id))
                        return

                prefix = "/v1/plugins/"
                suffix = "/test"

                if path.startswith(prefix) and path.endswith(suffix):
                    identifier = path[len(prefix) : -len(suffix)]

                    if identifier and "/" not in identifier:
                        self._execute(lambda: service.test_plugin(identifier))
                        return

                if path == "/v1/plugins/backup/icloud/connect":
                    payload = self._read_json()
                    if payload is not None:
                        self._execute(lambda: service.connect_backup_icloud(payload))
                    return

                backup_run_prefix = "/v1/plugins/backup/targets/"
                backup_run_suffix = "/run"
                if path.startswith(backup_run_prefix) and path.endswith(
                    backup_run_suffix
                ):
                    target_id = path[len(backup_run_prefix) : -len(backup_run_suffix)]
                    if target_id and "/" not in target_id:
                        self._execute(partial(service.run_backup, target_id))
                        return

                network_prefix = "/v1/system/network/"
                for action, operation in (
                    ("confirm", service.confirm_network),
                    ("rollback", service.rollback_network),
                ):
                    action_suffix = f"/{action}"
                    if path.startswith(network_prefix) and path.endswith(action_suffix):
                        transaction_id = path[len(network_prefix) : -len(action_suffix)]
                        if transaction_id and "/" not in transaction_id:
                            self._execute(partial(operation, transaction_id))
                            return

                self._write_error(
                    HTTPStatus.NOT_FOUND,
                    "Administration endpoint not found",
                )

            def log_message(
                self,
                format: str,
                *args: object,
            ) -> None:
                """Route request logs through Python logging."""
                LOGGER.info(
                    "%s - %s",
                    self.address_string(),
                    format % args,
                )

            def _authorized(self, token: str | None, role: str) -> bool:
                authorization = self.headers.get("Authorization", "")
                prefix = "Bearer "

                if (
                    token is None
                    or not authorization.startswith(prefix)
                    or not hmac.compare_digest(
                        authorization.removeprefix(prefix),
                        token,
                    )
                ):
                    self._write_error(
                        HTTPStatus.UNAUTHORIZED,
                        f"A valid {role} token is required",
                    )
                    return False

                return True

            def _authorized_worker(
                self,
                payload: dict[str, Any],
                *,
                previous_worker_id: str | None = None,
            ) -> bool:
                authorization = self.headers.get("Authorization", "")
                prefix = "Bearer "
                worker_id = payload.get("worker_id")
                supplied_token = authorization.removeprefix(prefix)
                shared_matches = (
                    expected_worker_token is not None
                    and authorization.startswith(prefix)
                    and hmac.compare_digest(supplied_token, expected_worker_token)
                )
                paired_matches = (
                    isinstance(worker_id, str)
                    and authorization.startswith(prefix)
                    and service.job_repository is not None
                    and service.job_repository.authorize_worker(
                        worker_id,
                        supplied_token,
                        previous_worker_id=previous_worker_id,
                    )
                )
                authorized = (
                    paired_matches
                    if previous_worker_id is not None
                    else shared_matches or paired_matches
                )
                if not authorized:
                    self._write_error(
                        HTTPStatus.UNAUTHORIZED,
                        "A valid worker token is required",
                    )
                    return False
                return True

            def _companion_identity(self) -> str | None:
                """Authorize only one paired companion on the limited listener."""
                device_id = self.headers.get("X-Ohana-Companion-Id", "").strip()
                authorization = self.headers.get("Authorization", "")
                prefix = "Bearer "
                supplied_token = authorization.removeprefix(prefix)
                authorized = (
                    bool(device_id)
                    and authorization.startswith(prefix)
                    and service.companion_repository is not None
                    and service.companion_repository.authorize(
                        device_id, supplied_token
                    )
                )
                if not authorized:
                    self._write_error(
                        HTTPStatus.UNAUTHORIZED,
                        "A valid companion session is required",
                    )
                    return None
                return device_id

            def _worker_transfer_identity(self) -> tuple[str, int] | None:
                worker_id = self.headers.get("X-Ohana-Worker-Id", "").strip()
                try:
                    attempt = int(self.headers.get("X-Ohana-Attempt", "0"))
                except ValueError:
                    attempt = 0
                payload = {"worker_id": worker_id}
                if not worker_id:
                    self._write_error(HTTPStatus.BAD_REQUEST, "Worker ID is required")
                    return None
                if attempt < 1:
                    self._write_error(HTTPStatus.BAD_REQUEST, "Invalid job attempt")
                    return None
                if not self._authorized_worker(payload):
                    return None
                return worker_id, attempt

            def _download_backup_source(self, job_id: str) -> None:
                identity = self._worker_transfer_identity()
                if identity is None:
                    return
                worker_id, attempt = identity
                response_started = False
                try:
                    with service.open_backup_source(
                        job_id, worker_id, attempt
                    ) as stream:
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/x-tar")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.close_connection = True
                        response_started = True
                        stream(self.wfile)
                except LookupError as error:
                    if response_started:
                        LOGGER.exception("Distributed backup source stream failed")
                    else:
                        self._write_error(HTTPStatus.NOT_FOUND, str(error))
                    return
                except DistributedJobConflictError as error:
                    if response_started:
                        LOGGER.exception("Distributed backup source stream failed")
                    else:
                        self._write_error(HTTPStatus.CONFLICT, str(error))
                    return
                except (BrokenPipeError, ConnectionError, OSError):
                    LOGGER.exception("Distributed backup source stream failed")
                except RuntimeError as error:
                    if response_started:
                        LOGGER.exception("Distributed backup source stream failed")
                    else:
                        LOGGER.exception(
                            "Distributed backup source preparation failed for job %s "
                            "(stage=%s)",
                            job_id,
                            getattr(error, "stage", "unknown"),
                        )
                        status = (
                            HTTPStatus.INSUFFICIENT_STORAGE
                            if getattr(error, "stage", None) == "storage"
                            else HTTPStatus.INTERNAL_SERVER_ERROR
                        )
                        self._write_error(
                            status,
                            f"Distributed backup source preparation failed: {error}",
                        )

            def _upload_backup_artifact(self, job_id: str) -> None:
                identity = self._worker_transfer_identity()
                if identity is None:
                    return
                worker_id, attempt = identity
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._write_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
                    return
                sha256 = self.headers.get("X-Ohana-SHA256", "").strip().lower()
                self._execute(
                    lambda: service.receive_backup_artifact(
                        job_id,
                        worker_id,
                        attempt,
                        _BoundedRequestStream(self.rfile, content_length),
                        content_length,
                        sha256,
                    )
                )

            def _read_json(self) -> dict[str, Any] | None:
                raw_length = self.headers.get("Content-Length")

                try:
                    content_length = int(raw_length or "0")
                except ValueError:
                    self._write_error(
                        HTTPStatus.BAD_REQUEST,
                        "Invalid Content-Length header",
                    )
                    return None

                if content_length <= 0 or content_length > MAXIMUM_REQUEST_BYTES:
                    self._write_error(
                        HTTPStatus.BAD_REQUEST,
                        "Administration request body size is invalid",
                    )
                    return None

                try:
                    payload = json.loads(
                        self.rfile.read(content_length).decode("utf-8")
                    )
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._write_error(
                        HTTPStatus.BAD_REQUEST,
                        "Administration request body must be valid JSON",
                    )
                    return None

                if not isinstance(payload, dict):
                    self._write_error(
                        HTTPStatus.BAD_REQUEST,
                        "Administration request body must be a JSON object",
                    )
                    return None

                return payload

            def _execute(
                self,
                operation: Callable[[], object],
            ) -> None:
                try:
                    result = operation()
                except LookupError as error:
                    self._write_error(
                        HTTPStatus.NOT_FOUND,
                        str(error),
                    )
                    return
                except (
                    CompanionConflictError,
                    DistributedJobConflictError,
                    TsunadeExpertiseConflictError,
                ) as error:
                    self._write_error(
                        HTTPStatus.CONFLICT,
                        str(error),
                    )
                    return
                except (
                    DHCPConfigurationError,
                    NetworkAdministrationError,
                    BackupExecutionError,
                    ValidationError,
                    ValueError,
                ) as error:
                    self._write_error(
                        HTTPStatus.UNPROCESSABLE_ENTITY,
                        str(error),
                    )
                    return
                except OSError as error:
                    LOGGER.exception("Administration operation failed")
                    self._write_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        f"Unable to apply administration operation: {error}",
                    )
                    return

                self._write_json(
                    HTTPStatus.OK,
                    result,
                )

            def _write_error(
                self,
                status: HTTPStatus,
                detail: str,
            ) -> None:
                self._write_json(
                    status,
                    {
                        "detail": detail,
                    },
                )

            def _write_json(
                self,
                status: HTTPStatus,
                payload: object,
            ) -> None:
                if hasattr(payload, "model_dump"):
                    payload = payload.model_dump(  # type: ignore[union-attr]
                        mode="json"
                    )

                content = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.send_response(status)
                self.send_header(
                    "Content-Type",
                    "application/json; charset=utf-8",
                )
                self.send_header(
                    "Content-Length",
                    str(len(content)),
                )
                self.end_headers()
                self.wfile.write(content)

        return AdministrationRequestHandler


class AdministrationServerGroup:
    """Start and stop the local administration and worker HTTPS listeners together."""

    def __init__(self, *servers: AdministrationHTTPServer) -> None:
        if not servers:
            raise ValueError("At least one administration server is required")
        self.servers = servers

    def start(self) -> None:
        started: list[AdministrationHTTPServer] = []
        try:
            for server in self.servers:
                server.start()
                started.append(server)
        except Exception:
            for server in reversed(started):
                server.stop()
            raise

    def stop(self) -> None:
        for server in reversed(self.servers):
            server.stop()


def certificate_sha256(path: Path) -> tuple[str, str]:
    """Read one public PEM certificate and return its normalized SHA-256."""
    pem = path.read_text(encoding="ascii")
    der = ssl.PEM_cert_to_DER_cert(pem)
    return pem, hashlib.sha256(der).hexdigest()
