"""Application service connecting public operations to Agent domains."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from threading import RLock
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from ohana_agent.companions.repository import (
    CompanionRepository,
)
from ohana_agent.configuration.administration import DistributedLogAnalysisConfig
from ohana_agent.configuration.builders.network import (
    NetworkConfigurationBuilder,
)
from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.configuration.network import NetworkPluginConfig
from ohana_agent.contracts.administration import (
    AdministrationCapabilities,
    DHCPConfiguration,
    LogsInvestigationAuthorization,
)
from ohana_agent.host.dhcp import DnsmasqDHCPRepository
from ohana_agent.host.network import (
    NetworkManagerRepository,
)
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.jobs.job_types import (
    AUTOMATIC_WAKE_JOB_TYPES,
    LOCAL_TIMEZONE,
    DistributedJobConflictError,
)
from ohana_agent.jobs.log_sources import LogSourceBroker
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.plugins.administration import PluginAdministrationRepository
from ohana_agent.tsunade.evidence_privacy import redact_session_paths
from ohana_agent.tsunade.expertise import (
    TsunadeExpertiseService,
)
from ohana_agent.tsunade.expertise_catalog import (
    TsunadeExpertiseConflictError,
)
from ohana_agent.tsunade.followups import TsunadeFollowupService
from ohana_agent.tsunade.incident_models import (
    TsunadeIncident,
    TsunadeRepairDecisionRequest,
    TsunadeRepairProposalRequest,
)
from ohana_agent.tsunade.incident_summary import (
    followup_covers_observation,
    incident_assessment,
)
from ohana_agent.tsunade.incidents import (
    TsunadeIncidentRepository,
)
from ohana_agent.tsunade.investigations import (
    InvestigationExecutor,
    InvestigationRequest,
    investigation_summary,
)
from ohana_agent.tsunade.local_time import paris_now
from ohana_agent.tsunade.repair_catalog import eligible_repair, repair_spec

LOGGER = logging.getLogger(__name__)
# A sleeping worker never polls: deadlines are also settled on this cadence.
JOB_SETTLEMENT_INTERVAL = timedelta(seconds=30)


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
        wake_broadcast_address: str | None = None,
        wake_port: int = 9,
        wake_available_for_seconds: int = 30,
        wake_packet_burst_count: int = 3,
        wake_burst_interval_seconds: float = 0.1,
        wake_retry_count: int = 2,
        wake_retry_delay_seconds: float = 1.0,
        wake_retry_sleeper: Callable[[float], None] = time.sleep,
        wake_batch_window_seconds: int = 600,
        wake_planned_window_start_hour: int = 0,
        wake_planned_window_end_hour: int = 5,
        wake_schedule_timezone: str = "Europe/Paris",
        wake_minimum_interval_seconds: int = 7200,
        wake_shutdown_after_completion: bool = True,
        wake_worker_id: str | None = None,
        wake_mac_address: str | None = None,
        backup_transfer: Any | None = None,
        incident_repository: TsunadeIncidentRepository | None = None,
        investigation_executor: InvestigationExecutor | None = None,
        log_source_broker: LogSourceBroker | None = None,
        expertise_service: TsunadeExpertiseService | None = None,
        log_sources: tuple[str, ...] = (),
        log_analysis_enabled: bool | None = None,
        log_analysis_schedule: str = "0 5 * * *",
        log_window_hours: int = 24,
        log_max_bytes: int = 2 * 1024 * 1024,
        log_timeout_seconds: int = 900,
        automatic_read_only_investigations: bool = False,
        on_log_analysis_changed: (
            Callable[[DistributedLogAnalysisConfig], None] | None
        ) = None,
        companion_repository: CompanionRepository | None = None,
        companion_ca_sha256: str | None = None,
        companion_ca_certificate_pem: str | None = None,
        notification_publisher: Callable[[dict[str, Any]], None] | None = None,
        repair_executors: (
            dict[str, Callable[[TsunadeIncident, str], None]] | None
        ) = None,
        repair_verification_requester: (
            Callable[[TsunadeIncident], None] | None
        ) = None,
        wake_enabled: bool = False,
        on_wake_enabled_changed: Callable[[bool], None] | None = None,
        agent_node_id: str | None = None,
    ) -> None:
        self.infrastructure_repository = infrastructure_repository
        self.dhcp_repository = dhcp_repository
        # Repairs acting on the Agent host only apply to services declared there.
        self.agent_node_id = agent_node_id or (
            dhcp_repository.server_node_id if dhcp_repository is not None else None
        )
        # One concrete executor per catalogue repair; nothing else can run.
        self.repair_executors = dict(repair_executors or {})
        if dhcp_repository is not None:
            self.repair_executors.setdefault(
                "dnsmasq.restart",
                lambda _incident, _target: dhcp_repository.request_supervised_restart(),
            )
        # Asks for prompt observations of the repaired capability.
        self.repair_verification_requester = repair_verification_requester
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
        self.wake_broadcast_address = wake_broadcast_address
        self.wake_port = wake_port
        self.wake_available_for_seconds = wake_available_for_seconds
        self.wake_packet_burst_count = wake_packet_burst_count
        self.wake_burst_interval_seconds = wake_burst_interval_seconds
        self.wake_retry_count = wake_retry_count
        self.wake_retry_delay_seconds = wake_retry_delay_seconds
        self.wake_retry_sleeper = wake_retry_sleeper
        self.wake_batch_window_seconds = wake_batch_window_seconds
        if not 0 <= wake_planned_window_start_hour < wake_planned_window_end_hour <= 24:
            raise ValueError("planned Wake-on-LAN window must be between 0 and 24")
        self.wake_planned_window_start_hour = wake_planned_window_start_hour
        self.wake_planned_window_end_hour = wake_planned_window_end_hour
        try:
            self.wake_schedule_timezone = ZoneInfo(wake_schedule_timezone)
        except Exception as error:
            raise ValueError("invalid Wake-on-LAN schedule timezone") from error
        self.wake_schedule_timezone_name = wake_schedule_timezone
        self.wake_minimum_interval_seconds = wake_minimum_interval_seconds
        self.wake_shutdown_after_completion = wake_shutdown_after_completion
        self.wake_worker_id = wake_worker_id
        self.wake_mac_address = wake_mac_address
        self._last_planned_wake_date = None
        self._last_job_settlement: datetime | None = None
        self.backup_transfer = backup_transfer
        self.incident_repository = incident_repository
        self.investigation_executor = investigation_executor
        self.log_source_broker = log_source_broker
        self.expertise_service = expertise_service
        self._worker_cycle_lock = RLock()
        self.log_analysis_enabled = (
            bool(log_sources) if log_analysis_enabled is None else log_analysis_enabled
        )
        self.log_analysis_schedule = log_analysis_schedule
        self.log_sources = tuple(log_sources)
        self.log_window_hours = log_window_hours
        self.log_max_bytes = log_max_bytes
        self.log_timeout_seconds = log_timeout_seconds
        self.on_log_analysis_changed = on_log_analysis_changed
        self.companion_repository = companion_repository
        self.companion_ca_sha256 = companion_ca_sha256
        self.companion_ca_certificate_pem = companion_ca_certificate_pem
        if (companion_ca_sha256 is None) != (companion_ca_certificate_pem is None):
            raise ValueError(
                "Companion CA certificate and fingerprint must be configured together"
            )
        self.notification_publisher = notification_publisher
        self.wake_enabled = wake_enabled
        self.on_wake_enabled_changed = on_wake_enabled_changed
        self.followups = (
            TsunadeFollowupService(
                incident_repository,
                job_repository,
                expertise_service,
                self.create_job,
                lambda: (
                    self.log_analysis_enabled,
                    self.log_sources,
                    self.log_max_bytes,
                    self.log_timeout_seconds,
                ),
                self._publish_notification,
                automatic_read_only=automatic_read_only_investigations,
            )
            if incident_repository is not None
            and job_repository is not None
            and expertise_service is not None
            else None
        )

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
                    "jobs.wake_on_lan.read",
                    "jobs.wake_on_lan.write",
                    "jobs.worker.pair",
                    "jobs.worker.register",
                    "jobs.worker.claim",
                    "jobs.worker.heartbeat",
                    "jobs.worker.complete",
                ]
            )
            if self.wake_enabled and self.wake_sender is not None:
                operations.append("jobs.workers.wake")

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
        if self.job_repository is not None:
            operations.extend(["incidents.logs.read", "incidents.logs.write"])
            if self.log_analysis_enabled and self.log_sources:
                operations.extend(
                    ["incidents.logs.check", "incidents.logs.investigate"]
                )
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

        if self.incident_repository is not None:
            saved_network_devices = {
                device.name
                for device in NetworkConfigurationBuilder()
                .build(saved_configuration, NetworkPluginConfig())
                .devices
                if device.enabled
            }
            self.incident_repository.reconcile_network_devices(
                saved_network_devices,
                occurred_at=datetime.now(ZoneInfo("Europe/Paris")),
            )

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
        self._refresh_failed_jobs()
        if self.followups is not None and self.followups.automatic_read_only:
            self._reconcile_followup_proposals()
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
                {
                    **incident.model_dump(mode="json"),
                    "assessment": incident_assessment(incident),
                }
                for incident in self.incident_repository.list(state=state)
            ],
        }

    def read_incident(self, incident_id: str) -> object:
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        self._refresh_failed_jobs()
        return self.incident_repository.get(incident_id)

    def read_companion_summary(self) -> object:
        """Return the smallest useful Konoha overview for a personal companion."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        self._refresh_failed_jobs()
        self._reconcile_followup_proposals()
        requests = self.incident_repository.list_user_requests(state="pending").requests
        incidents = self.incident_repository.list(state="active", limit=500)
        incidents.sort(
            key=lambda incident: (
                incident_assessment(incident)["priority"],
                incident.started_at,
            )
        )
        totals = self.incident_repository.statistics()
        active_count = totals["incident_count"] - totals["resolved_incident_count"]
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
            "Aucune autorisation en attente"
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
                "assessment": incident_assessment(incident),
            }
            for incident in incidents[:20]
        ]
        return {
            "schema_version": 1,
            "konoha_state": severity,
            "tsunade_message": message,
            "pending_requests": pending_count,
            "last_checked_at": last_checked_at.isoformat() if last_checked_at else None,
            "attention": attention,
            "active_count": active_count,
            "attention_truncated": active_count > len(attention),
        }

    def read_companion_requests(self, state: str = "pending") -> object:
        """Expose structured Tsunade questions without technical incident payloads."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        self._reconcile_followup_proposals()
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
                        "detail": (
                            "Aucune anomalie relevée dans les sources contrôlées."
                            if latest.result and latest.result.get("status") == "OK"
                            else "Anomalies ou sources indisponibles à examiner."
                        )
                        if latest.status.value == "SUCCEEDED"
                        else "Le contrôle n’a pas abouti.",
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
        if set(payload) != {"choice"}:
            raise ValueError("Seul le choix proposé par Tsunade est accepté")
        choice = str(payload.get("choice") or "").upper()
        request = self.incident_repository.get_user_request(request_id)
        response = {
            "choice": choice,
            "source": "shizune",
            "answered_by": device_id,
        }
        if choice == "LATER":
            return self.incident_repository.defer_user_request(request_id, response)
        if request.kind == "investigation_authorization":
            if self.followups is None:
                raise LookupError(
                    "Les investigations complémentaires sont indisponibles"
                )
            with self._worker_cycle_lock:
                return self.followups.respond(request_id, device_id, choice)
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
        """Run the bounded expertise cycle explicitly requested by an operator."""
        if self.expertise_service is None:
            raise LookupError("Tsunade expertise is unavailable")
        with self._worker_cycle_lock:
            self._refresh_failed_jobs()
            if self.followups is not None and self.followups.automatic_read_only:
                self._reconcile_followup_proposals()
            if self.incident_repository is not None:
                incident = self.incident_repository.get(incident_id)
                followup = incident.followup or {}
                if followup.get("status") in {
                    "pending",
                    "authorized",
                    "queued",
                    "reviewing",
                }:
                    raise ValueError(
                        "Une collecte attend votre autorisation dans Shizune "
                        "ou est déjà en cours. Consultez son suivi."
                    )
                if followup.get("status") in {
                    "completed",
                    "incomplete",
                } and followup_covers_observation(incident):
                    raise ValueError(
                        "La collecte complémentaire a déjà été réévaluée. "
                        "Un nouveau périmètre ou de nouvelles observations sont "
                        "nécessaires ; relancer les mêmes données ne l’approfondit pas."
                    )
            return self.expertise_service.diagnose(
                incident_id,
                operator_requested=True,
            )

    def request_companion_diagnosis(self, incident_id: str, device_id: str) -> object:
        """Accept a bounded diagnostic request, never a repair authorization."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        outcome = self.diagnose_incident(incident_id)
        self.incident_repository.append_record(
            incident_id,
            {
                "kind": "investigation",
                "summary": "Diagnostic demandé depuis Shizune.",
                "payload": {"source": "shizune", "requested_by": device_id},
            },
        )
        return {"schema_version": 1, "status": outcome.status}

    def propose_incident_repair(
        self,
        incident_id: str,
        payload: dict[str, Any],
        *,
        automatic: bool = False,
    ) -> object:
        """Let Tsunade select the catalogue repair whose preconditions hold."""
        if self.incident_repository is None:
            raise LookupError("Les réparations supervisées sont indisponibles")
        request = TsunadeRepairProposalRequest.model_validate(payload)
        incident = self.incident_repository.get(incident_id)
        if automatic and incident.repairs:
            # After a refusal, expiry or failure only a human asks again.
            return None
        spec = eligible_repair(
            incident,
            self.infrastructure_repository.read(),
            agent_node_id=self.agent_node_id,
        )
        if request.operation not in (None, spec.operation):
            raise ValueError("Cette opération ne correspond pas à la réparation connue")
        if spec.key not in self.repair_executors:
            raise LookupError("L’exécution de cette réparation n’est pas configurée")
        repair = self.incident_repository.propose_repair(incident_id, spec)
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
        if self.incident_repository is None:
            raise LookupError("Les réparations supervisées sont indisponibles")
        repair = self.incident_repository.authorize_repair(incident_id, payload)
        try:
            spec = repair_spec(repair.operation, repair.target)
            executor = self.repair_executors.get(spec.key) if spec else None
            if executor is None:
                raise LookupError("Aucun exécuteur pour cette réparation")
            executor(self.incident_repository.get(incident_id), repair.target)
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
                    "occurred_at": paris_now().isoformat(),
                }
            )
            return result
        executed = self.incident_repository.mark_repair_executed(repair.repair_id)
        if self.repair_verification_requester is not None:
            try:
                self.repair_verification_requester(
                    self.incident_repository.get(incident_id)
                )
            except Exception:  # noqa: BLE001
                # The scheduled observation and the deadline still apply.
                LOGGER.exception("Unable to request the repair verification")
        return executed

    def refuse_incident_repair(
        self, incident_id: str, payload: dict[str, Any]
    ) -> object:
        """Record an explicit refusal; the proposal can never run afterwards."""
        if self.incident_repository is None:
            raise LookupError("Les réparations supervisées sont indisponibles")
        request = TsunadeRepairDecisionRequest.model_validate(payload)
        return self.incident_repository.refuse_repair(
            incident_id,
            request.repair_id,
            source=request.source,
            answered_by=request.answered_by,
        )

    def defer_incident_repair(
        self, incident_id: str, payload: dict[str, Any]
    ) -> object:
        """Keep a proposal pending for a bounded delay, without executing it."""
        if self.incident_repository is None:
            raise LookupError("Les réparations supervisées sont indisponibles")
        request = TsunadeRepairDecisionRequest.model_validate(payload)
        incident = self.incident_repository.get(incident_id)
        repair = next(
            (item for item in incident.repairs if item.repair_id == request.repair_id),
            None,
        )
        if repair is None:
            raise LookupError("Proposition de réparation inconnue")
        request_id = self.incident_repository.repair_request_id(repair.repair_id)
        if repair.status != "proposed" or request_id is None:
            raise ValueError("Cette réparation n’attend plus de validation")
        self.incident_repository.defer_user_request(
            request_id,
            {
                "choice": "LATER",
                "source": request.source,
                "answered_by": request.answered_by,
            },
        )
        return next(
            item
            for item in self.incident_repository.get(incident_id).repairs
            if item.repair_id == repair.repair_id
        )

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
        if (
            self.job_repository is None
            or not self.log_analysis_enabled
            or not self.log_sources
        ):
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
        current = now or datetime.now(LOCAL_TIMEZONE)
        if current.tzinfo is None or current.utcoffset() is None:
            current = current.replace(tzinfo=LOCAL_TIMEZONE)
        else:
            current = current.astimezone(LOCAL_TIMEZONE)
        selected_window = window_hours or self.log_window_hours
        window_started = current - timedelta(hours=selected_window)
        baseline: list[dict[str, object]] = []
        previous_sources = self.job_repository.latest_log_health_sources(
            selected_sources,
            window_seconds=int(current.timestamp() - window_started.timestamp()),
        )
        for source in previous_sources:
            if not isinstance(source, dict):
                continue
            for finding in source.get("findings", []):
                if isinstance(finding, dict) and len(baseline) < 192:
                    baseline.append(
                        {
                            "source": source.get("source"),
                            "signature": (
                                redact_session_paths(finding["signature"])
                                if isinstance(finding.get("signature"), str)
                                else finding.get("signature")
                            ),
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
                    "window_started_at": window_started.isoformat(),
                    "window_ended_at": current.isoformat(),
                    "max_bytes_per_source": max_bytes or self.log_max_bytes,
                    "baseline": baseline,
                    "incident_id": None,
                },
                "timeout": timeout_seconds or self.log_timeout_seconds,
            }
        )

    def read_log_analysis(self) -> object:
        """Expose the effective scheduled Tsunade log-control policy."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return {
            "schema_version": 1,
            "enabled": self.log_analysis_enabled,
            "schedule": self.log_analysis_schedule,
            "sources": list(self.log_sources),
            "window_hours": self.log_window_hours,
            "max_bytes_per_source": self.log_max_bytes,
            "timeout_seconds": self.log_timeout_seconds,
        }

    def write_log_analysis(self, payload: dict[str, Any]) -> object:
        """Enable, disable or reschedule the bounded Tsunade log control."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")

        configuration = DistributedLogAnalysisConfig.model_validate(payload)

        if self.on_log_analysis_changed is not None:
            self.on_log_analysis_changed(configuration)

        self.log_analysis_enabled = configuration.enabled
        self.log_analysis_schedule = configuration.schedule
        self.log_sources = configuration.sources
        self.log_window_hours = configuration.window_hours
        self.log_max_bytes = configuration.max_bytes_per_source
        self.log_timeout_seconds = configuration.timeout_seconds

        return self.read_log_analysis()

    def request_log_investigation(
        self, incident_id: str, payload: dict[str, Any]
    ) -> object:
        """Queue an operator-authorized follow-up for one log incident."""
        if (
            self.job_repository is None
            or not self.log_analysis_enabled
            or not self.log_sources
        ):
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
                    "summary": investigation_summary(result),
                    "payload": result.model_dump(mode="json"),
                },
            )
        return result

    def create_job(self, payload: dict[str, Any]) -> object:
        """Validate and queue one explicitly typed distributed job."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        payload = self._extend_job_timeout_until_planned_wake(payload)
        job = self.job_repository.create(payload)
        self.dispatch_due_wake_requests()
        return job

    def _extend_job_timeout_until_planned_wake(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Keep grouped Katsuyu jobs alive until the planned wake boundary."""
        if (
            not self.wake_enabled
            or self.wake_planned_window_end_hour >= 24
            or payload.get("type") not in AUTOMATIC_WAKE_JOB_TYPES
        ):
            return payload
        try:
            timeout_seconds = int(payload["timeout"])
            created_at = datetime.fromisoformat(str(payload["created_at"]))
        except (KeyError, TypeError, ValueError):
            return payload
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            created_at = created_at.replace(tzinfo=LOCAL_TIMEZONE)
        current = created_at.astimezone(self.wake_schedule_timezone)
        if not (
            self.wake_planned_window_start_hour
            <= current.hour
            < self.wake_planned_window_end_hour
        ):
            return payload
        planned_wake = current.replace(
            hour=self.wake_planned_window_end_hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        seconds_until_wake = math.ceil((planned_wake - current).total_seconds())
        if seconds_until_wake <= 0:
            return payload
        extended = dict(payload)
        extended["timeout"] = (
            timeout_seconds + seconds_until_wake + self.wake_timeout_seconds
        )
        return extended

    def settle_expired_jobs(self, now: datetime | None = None) -> None:
        """Record elapsed deadlines while no worker or page reads the queue."""
        if self.job_repository is None:
            return
        current = now or self.job_repository.now()
        if (
            self._last_job_settlement is not None
            and current - self._last_job_settlement < JOB_SETTLEMENT_INTERVAL
        ):
            return
        # A busy worker cycle settles the queue itself; never stall the scheduler.
        if not self._worker_cycle_lock.acquire(blocking=False):
            return
        try:
            self._last_job_settlement = current
            self._refresh_failed_jobs()
        finally:
            self._worker_cycle_lock.release()

    def dispatch_due_wake_requests(self, now: datetime | None = None) -> None:
        """Wake one worker at the local daily Katsuyu batch boundary."""
        if self.job_repository is None:
            return
        current = (now or self.job_repository.now()).astimezone(
            self.wake_schedule_timezone
        )
        if (
            self.wake_planned_window_end_hour < 24
            and current.hour != self.wake_planned_window_end_hour
        ):
            return
        batch_date = current.date()
        if self._last_planned_wake_date == batch_date:
            return
        woke_worker = False
        for job_type in self.job_repository.wake_ready_job_types(
            batch_window_seconds=0,
            job_types=AUTOMATIC_WAKE_JOB_TYPES,
        ):
            woke_worker = self._wake_compatible_worker(job_type) or woke_worker
        if woke_worker:
            self._last_planned_wake_date = batch_date

    def _wake_compatible_worker(self, job_type: str) -> bool:
        """Wake one unavailable compatible worker using its advertised WOL MAC."""
        if (
            self.job_repository is None
            or not self.wake_enabled
            or self.wake_sender is None
        ):
            return False
        worker = self.job_repository.wake_candidate(
            job_type,
            minimum_interval_seconds=self.wake_minimum_interval_seconds,
            fallback_worker_id=self.wake_worker_id,
            fallback_mac_address=self.wake_mac_address,
        )
        if worker is None or worker.wake_on_lan_mac_address is None:
            return False
        try:
            self._send_wake_on_lan(worker.wake_on_lan_mac_address)
            self.job_repository.mark_worker_waking(
                worker.worker_id,
                timeout_seconds=self.wake_timeout_seconds,
            )
            return True
        except (OSError, ValueError):
            LOGGER.exception(
                "Unable to send Wake-on-LAN for Katsuyu worker %s",
                worker.worker_id,
            )
            return False

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
        return self.job_repository.claim(
            payload,
            # Legacy workers cannot re-check the queue after publishing results.
            shutdown_after_completion=False,
        )

    def next_worker_job(self, payload: dict[str, Any]) -> object:
        """Settle results before claiming work or allowing shutdown."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        with self._worker_cycle_lock:
            if self.followups is not None:
                self.followups.resume()
            for job in self.job_repository.pending_completions():
                self._process_job_completion(job)
            return self.job_repository.claim(
                payload,
                settle=True,
                shutdown_after_completion=self.wake_shutdown_after_completion,
            )

    def register_worker(
        self,
        payload: dict[str, Any],
        *,
        previous_worker_id: str | None = None,
    ) -> object:
        """Register Katsuyu and its finite capabilities."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        if (
            payload.get("worker_id") == self.wake_worker_id
            and payload.get("wake_on_lan_mac_address") is None
            and self.wake_mac_address is not None
        ):
            payload = dict(payload)
            payload["wake_on_lan_mac_address"] = self.wake_mac_address
        return self.job_repository.register_worker(
            payload,
            previous_worker_id=previous_worker_id,
        )

    def list_workers(self) -> object:
        """List the worker registrations visible to Tsunade."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.list_workers()

    def read_wake_on_lan(self) -> object:
        """Expose the effective Wake-on-LAN policy without duplicating worker data."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return {
            "schema_version": 1,
            "enabled": self.wake_enabled,
            "broadcast_address": self.wake_broadcast_address,
            "port": self.wake_port,
            "wait_timeout_seconds": self.wake_timeout_seconds,
            "available_for_seconds": self.wake_available_for_seconds,
            "packet_burst_count": self.wake_packet_burst_count,
            "burst_interval_seconds": self.wake_burst_interval_seconds,
            "retry_count": self.wake_retry_count,
            "retry_delay_seconds": self.wake_retry_delay_seconds,
            "batch_window_seconds": self.wake_batch_window_seconds,
            "planned_window_start_hour": self.wake_planned_window_start_hour,
            "planned_window_end_hour": self.wake_planned_window_end_hour,
            "schedule_timezone": self.wake_schedule_timezone_name,
            "minimum_interval_seconds": self.wake_minimum_interval_seconds,
            "shutdown_after_completion": self.wake_shutdown_after_completion,
        }

    def write_wake_on_lan(self, payload: dict[str, Any]) -> object:
        """Enable or disable Agent-owned Wake-on-LAN policy."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")

        if set(payload) != {"enabled"}:
            raise ValueError("Wake-on-LAN update only accepts enabled")

        enabled = payload["enabled"]

        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")

        if enabled:
            workers = self.job_repository.list_workers()

            if not any(worker.wake_on_lan_mac_address for worker in workers.workers):
                raise DistributedJobConflictError(
                    "Wake-on-LAN cannot be enabled because no "
                    "worker has advertised a Wake-on-LAN MAC "
                    "address"
                )

        if self.on_wake_enabled_changed is not None:
            self.on_wake_enabled_changed(enabled)

        self.wake_enabled = enabled

        return self.read_wake_on_lan()

    def wake_worker(self, worker_id: str) -> object:
        """Send one explicit Wake-on-LAN test to a registered Katsuyu worker."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        if not self.wake_enabled or self.wake_sender is None:
            raise DistributedJobConflictError("Wake-on-LAN is disabled")
        worker = self.job_repository.worker_availability(worker_id)
        mac_address = worker.wake_on_lan_mac_address
        if (
            mac_address is None
            and worker.worker_id == self.wake_worker_id
            and self.wake_mac_address is not None
        ):
            mac_address = self.wake_mac_address
        if mac_address is None:
            raise DistributedJobConflictError(
                f"worker {worker_id} has not advertised a Wake-on-LAN MAC address"
            )
        if worker.availability.value == "AVAILABLE":
            raise DistributedJobConflictError(
                f"worker {worker_id} is already available"
            )
        if worker.availability.value == "WAKING":
            return worker
        self._send_wake_on_lan(mac_address)
        self.job_repository.mark_worker_waking(
            worker.worker_id,
            timeout_seconds=self.wake_timeout_seconds,
        )
        return self.job_repository.worker_availability(worker.worker_id)

    def _send_wake_on_lan(self, mac_address: str) -> None:
        """Send Wake-on-LAN with bounded retries around the sender burst."""
        if self.wake_sender is None:
            raise DistributedJobConflictError("Wake-on-LAN is disabled")

        attempts = self.wake_retry_count + 1
        for attempt in range(attempts):
            try:
                self.wake_sender(mac_address)
                return
            except (OSError, ValueError):
                if attempt >= attempts - 1:
                    raise
                if self.wake_retry_delay_seconds > 0:
                    self.wake_retry_sleeper(self.wake_retry_delay_seconds)

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
        with self._worker_cycle_lock:
            job = self.job_repository.complete(job_id, payload)
            for pending in self.job_repository.pending_completions():
                if str(pending.job_id) == job_id:
                    self._process_job_completion(pending)
            return job

    def _refresh_failed_jobs(self) -> None:
        """Expose all terminal failures even when no worker polls again."""
        if self.job_repository is None:
            return
        with self._worker_cycle_lock:
            while True:
                pending = self.job_repository.pending_completions(failures_only=True)
                if not pending:
                    return
                for job in pending:
                    self._process_job_completion(job)

    def _process_job_completion(self, job: Any) -> None:
        """Commit decisions and follow-up jobs before releasing idle workers."""
        assert self.job_repository is not None
        if (
            job.status.value == "SUCCEEDED"
            and job.result is not None
            and self.incident_repository is not None
        ):
            incident_id = job.parameters.get("incident_id")
            if job.type == "logs.health_check":
                affected = self.incident_repository.record_log_health(
                    job.job_id,
                    job.result,
                    incident_id=incident_id,
                )
                if self.expertise_service is not None:
                    for target in affected:
                        try:
                            target_incident = self.incident_repository.get(target)
                            if target_incident.expertise_state == "ai_queued":
                                previous = self.job_repository.latest_for_incident(
                                    "ai.inference", str(target)
                                )
                                if previous is not None and previous.status.value in {
                                    "SUCCEEDED",
                                    "FAILED",
                                    "TIMEOUT",
                                    "CANCELLED",
                                }:
                                    self._process_job_completion(previous)
                                elif previous is None:
                                    self.expertise_service.record_ai_failure(
                                        target,
                                        job.job_id,
                                        "Analyse précédente introuvable",
                                    )
                            self.expertise_service.review_log_health(
                                target, job.job_id, job.result
                            )
                        except TsunadeExpertiseConflictError:
                            return
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
                        evidence=job.parameters.get("evidence"),
                    )
                    if self.followups is not None:
                        self.followups.consider(job)
        elif (
            job.type == "ai.inference"
            and job.parameters.get("incident_id") is not None
            and self.expertise_service is not None
            and job.status.value in {"FAILED", "TIMEOUT", "CANCELLED"}
        ):
            self.expertise_service.record_ai_failure(
                job.parameters["incident_id"],
                job.job_id,
                job.error.message if job.error is not None else job.status.value,
            )
        if self.followups is not None:
            self.followups.completed(job)
        self.job_repository.mark_completion_processed(str(job.job_id))

    def _reconcile_followup_proposals(self) -> None:
        """Make still-current persisted suggestions actionable after an upgrade."""
        if self.followups is None or self.incident_repository is None:
            return
        assert self.job_repository is not None
        with self._worker_cycle_lock:
            for incident in self.incident_repository.list():
                if (
                    incident.state != "active"
                    or incident.capability_id != "logs.health"
                ):
                    continue
                job = self.job_repository.latest_for_incident(
                    "ai.inference", str(incident.incident_id)
                )
                if job is not None and job.status.value == "SUCCEEDED":
                    self.followups.consider(job)

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
