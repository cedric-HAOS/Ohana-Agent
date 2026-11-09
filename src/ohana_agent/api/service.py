"""Application service connecting public operations to Agent domains."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

from ohana_agent.api.service_companion import CompanionServiceMixin
from ohana_agent.api.service_jobs import JobServiceMixin
from ohana_agent.api.service_logs import LogServiceMixin
from ohana_agent.api.service_preventive import PreventiveServiceMixin
from ohana_agent.api.service_system import SystemServiceMixin
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
)
from ohana_agent.host.adguard_sync import AdGuardSyncAdministration
from ohana_agent.host.dhcp import DnsmasqDHCPRepository
from ohana_agent.host.network import (
    NetworkManagerRepository,
)
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.jobs.log_sources import LogSourceBroker
from ohana_agent.jobs.power_plug import PowerPlugController
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.plugins.administration import PluginAdministrationRepository
from ohana_agent.runtime.memory_diagnostics import AllocationTrace
from ohana_agent.tsunade.expertise import (
    TsunadeExpertiseService,
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
)
from ohana_agent.tsunade.local_time import paris_now
from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor
from ohana_agent.tsunade.repair_catalog import eligible_repair, repair_spec

LOGGER = logging.getLogger(__name__)


class AdministrationService(
    CompanionServiceMixin,
    PreventiveServiceMixin,
    SystemServiceMixin,
    LogServiceMixin,
    JobServiceMixin,
):
    """Execute versioned administration operations owned by Agent."""

    def __init__(
        self,
        *,
        infrastructure_repository: InfrastructureConfigurationRepository,
        dhcp_repository: DnsmasqDHCPRepository | None = None,
        plugin_repository: PluginAdministrationRepository | None = None,
        network_repository: NetworkManagerRepository | None = None,
        adguard_sync_repository: AdGuardSyncAdministration | None = None,
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
        wake_unanswered_retry_seconds: int = 600,
        wake_max_unanswered_attempts: int = 3,
        wake_shutdown_after_completion: bool = True,
        wake_worker_id: str | None = None,
        wake_mac_address: str | None = None,
        backup_transfer: Any | None = None,
        incident_repository: TsunadeIncidentRepository | None = None,
        preventive_monitor: TsunadePreventiveMonitor | None = None,
        self_report: Callable[[], dict[str, Any]] | None = None,
        system_updates_reader: Callable[[], dict[str, Any]] | None = None,
        system_update_requester: Any | None = None,
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
        power_plug: PowerPlugController | None = None,
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
        self.adguard_sync_repository = (
            adguard_sync_repository or AdGuardSyncAdministration()
        )
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
        self.wake_unanswered_retry_seconds = wake_unanswered_retry_seconds
        self.wake_max_unanswered_attempts = wake_max_unanswered_attempts
        self.wake_shutdown_after_completion = wake_shutdown_after_completion
        self.wake_worker_id = wake_worker_id
        self.wake_mac_address = wake_mac_address
        # Smart plug feeding the wake worker's PC (only that worker's).
        self.power_plug = power_plug
        self._plug_worker: str | None = None
        self._last_planned_wake_date = None
        self._last_job_settlement: datetime | None = None
        self.backup_transfer = backup_transfer
        self.incident_repository = incident_repository
        self.preventive_monitor = preventive_monitor
        self.self_report = self_report
        self.system_updates_reader = system_updates_reader
        self.system_update_requester = system_update_requester
        self.allocation_trace = AllocationTrace()
        self._system_updates_cache: tuple[float, dict[str, Any]] | None = None
        self.investigation_executor = investigation_executor
        self.log_source_broker = log_source_broker
        # Phase 10: set by the bootstrap; verifies the latest published archives.
        self.archive_integrity: Any | None = None
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

        if self.adguard_sync_repository.helper.is_file():
            operations.extend(
                [
                    "system.adguard_sync.read",
                    "system.adguard_sync.write",
                    "system.adguard_sync.activation",
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
                    "incidents.experiences.read",
                    "incidents.experiences.state",
                    "incidents.manual_resolution.declare",
                ]
            )
            if self.dhcp_repository is not None:
                operations.extend(
                    ["incidents.repairs.propose", "incidents.repairs.authorize"]
                )
            operations.extend(
                [
                    "incidents.summary.read",
                    "incidents.history.read",
                    "incidents.requests.read",
                    "incidents.requests.respond",
                    "incidents.activity.read",
                ]
            )
        if self.self_report is not None:
            operations.append("agent.vitals.read")
        operations.extend(
            ["agent.diagnostics.memory.read", "agent.diagnostics.memory.trace"]
        )
        if self.system_updates_reader is not None:
            operations.append("system.updates.read")
            if self.system_update_requester is not None:
                operations.extend(["system.updates.refresh", "system.updates.apply"])
        if self.preventive_monitor is not None:
            operations.extend(
                [
                    "preventive.read",
                    "preventive.mute",
                    "backups.restore_tests.read",
                    "backups.restore_tests.declare",
                ]
            )
            if self.archive_integrity is not None:
                operations.append("backups.archives.verify")
            if self._preventive_backfill_available():
                operations.append("preventive.backfill")
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

    def read_adguard_sync(self) -> object:
        return self.adguard_sync_repository.read()

    def write_adguard_sync(self, payload: dict[str, Any]) -> object:
        return self.adguard_sync_repository.write(payload)

    def activate_adguard_sync(self, payload: dict[str, Any]) -> object:
        return self.adguard_sync_repository.set_enabled(payload)

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
        self._settle_for_read(
            reconcile=self.followups is not None and self.followups.automatic_read_only
        )
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
            "log_components": self.incident_repository.log_component_overview(
                latest_log_health["result"] if latest_log_health else None
            ),
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
        self._settle_for_read()
        return self.incident_repository.get(incident_id)

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

    def declare_manual_resolution(
        self, incident_id: str, payload: dict[str, Any]
    ) -> object:
        """Record a manual action and ask Shikamaru to verify it right away."""
        if self.incident_repository is None:
            raise LookupError("La mémoire des diagnostics est indisponible")
        action = self.incident_repository.declare_manual_resolution(
            incident_id, payload
        )
        if self.repair_verification_requester is not None:
            try:
                self.repair_verification_requester(
                    self.incident_repository.get(incident_id)
                )
            except Exception:  # noqa: BLE001
                # The scheduled observation and the deadline still apply.
                LOGGER.exception("Unable to request the manual action verification")
        return action

    def search_incident_history(self, payload: dict[str, Any]) -> object:
        """Phase 3: past and open incidents by equipment, capability, period."""
        return self._require_incidents().history(payload)

    def read_equipment_history(self, equipment_id: str) -> object:
        return self._require_incidents().equipment_history(equipment_id)

    def read_incident_timeline(self) -> object:
        return self._require_incidents().timeline(days=30)

    def read_similar_incidents(self, incident_id: str) -> object:
        return self._require_incidents().similar_incidents(incident_id)

    def _require_incidents(self) -> Any:
        if self.incident_repository is None:
            raise LookupError("Tsunade incident history is unavailable")
        return self.incident_repository

    def list_experiences(self) -> object:
        """List known repairs with their attempts, outcomes and state."""
        if self.incident_repository is None:
            raise LookupError("La mémoire des diagnostics est indisponible")
        return {
            "schema_version": 1,
            "experiences": [
                {**experience.model_dump(mode="json"), **ranking}
                for experience, ranking in self.incident_repository.ranked_experiences()
            ],
        }

    def read_repair_statistics(self) -> object:
        """Detailed success statistics and ranking of supervised repairs."""
        return self._require_incidents().repair_statistics()

    def set_experience_state(
        self, experience_id: str, payload: dict[str, Any]
    ) -> object:
        """Disable, retire or reactivate one known repair."""
        if self.incident_repository is None:
            raise LookupError("La mémoire des diagnostics est indisponible")
        return self.incident_repository.set_experience_state(experience_id, payload)
