"""Tsunade administration wiring: control API, Katsuyu jobs and companions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from ohana_agent.api.http import (
    AdministrationHTTPServer,
    AdministrationServerGroup,
    certificate_sha256,
)
from ohana_agent.api.service import AdministrationService
from ohana_agent.companions.notifications import APNsNotificationPublisher
from ohana_agent.companions.repository import CompanionRepository
from ohana_agent.configuration.administration import (
    AdministrationConfig,
    CompanionTLSConfig,
    DHCPAdministrationConfig,
    DistributedJobsConfig,
    DistributedLogAnalysisConfig,
    DistributedWorkerTLSConfig,
    NetworkAdministrationConfig,
    WakeOnLanConfig,
)
from ohana_agent.configuration.configuration import Configuration
from ohana_agent.configuration.loader import ConfigurationLoader
from ohana_agent.core.events import EventBus
from ohana_agent.host.dhcp import DnsmasqDHCPRepository
from ohana_agent.host.network import NetworkManagerRepository
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.jobs.log_sources import LogSourceBroker
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.jobs.wake_on_lan import WakeOnLanSender
from ohana_agent.observation import ObservationPublished, PluginObservationDispatcher
from ohana_agent.observation.exporters import VisionInfrastructureMapper
from ohana_agent.plugins.administration import PluginAdministrationRepository
from ohana_agent.plugins.backup.config import BackupConfig
from ohana_agent.plugins.backup.distributed_infra_backup import (
    DistributedInfraBackupCoordinator,
    DistributedInfraBackupTransfer,
)
from ohana_agent.plugins.mqtt.host_health import HostHealthMonitor
from ohana_agent.plugins.runtime.plugin_manager import PluginManager
from ohana_agent.runtime.agent import ProductionAgent
from ohana_agent.runtime.plugin_catalog import LOCAL_SCHEDULE_TIMEZONE
from ohana_agent.runtime.plugin_specs import ProductionPlugins, replace_plugin_tasks
from ohana_agent.scheduler import CronTrigger, IntervalTrigger, Scheduler, Task
from ohana_agent.scheduler.clock import Clock
from ohana_agent.tsunade.configuration_inspection import (
    configured_http_target,
    inspect_configuration,
    restart_addon,
)
from ohana_agent.tsunade.expertise import (
    TsunadeExpertiseService,
)
from ohana_agent.tsunade.incident_correlation import correlated_upstream_id
from ohana_agent.tsunade.incidents import (
    TsunadeIncidentRepository,
)
from ohana_agent.tsunade.investigations import InvestigationExecutor


@dataclass(frozen=True, slots=True)
class AdministrationContext:
    """Runtime pieces the administration API needs from the production agent."""

    configuration: Configuration
    application_config_path: Path
    infrastructure_config_path: Path
    plugins: ProductionPlugins
    plugin_manager: PluginManager
    scheduler: Scheduler
    dispatcher: PluginObservationDispatcher
    event_bus: EventBus
    host_health_monitor: HostHealthMonitor
    clock: Clock
    agent: ProductionAgent
    apply_plugin_configuration: Callable[[str, object], None]


@dataclass(frozen=True, slots=True)
class _CompanionRuntime:
    config: CompanionTLSConfig
    repository: CompanionRepository
    ca_certificate_pem: str
    ca_sha256: str
    notifications: APNsNotificationPublisher


@dataclass(frozen=True, slots=True)
class _WorkerTLS:
    config: DistributedWorkerTLSConfig
    ca_certificate_pem: str
    ca_sha256: str


def build_log_analysis_tasks(
    *,
    logs_config: DistributedLogAnalysisConfig,
    schedule_timezone: ZoneInfo | None = None,
) -> list[Task]:
    """Build the single configurable daily Tsunade log-control task."""
    if not logs_config.enabled:
        return []
    return [
        Task(
            id="tsunade.logs.health_check",
            name="Check Konoha logs with Katsuyu",
            command="jobs.logs.health_check",
            trigger=CronTrigger(logs_config.schedule, timezone=schedule_timezone),
            arguments={
                "sources": list(logs_config.sources),
                "window_hours": logs_config.window_hours,
                "max_bytes_per_source": logs_config.max_bytes_per_source,
                "timeout_seconds": logs_config.timeout_seconds,
            },
            metadata={
                "managed_by": "tsunade-logs",
                "schedule": logs_config.schedule,
            },
        )
    ]


def build_wake_dispatch_tasks(
    *, jobs_config: DistributedJobsConfig, start_at: datetime
) -> list[Task]:
    """Build the internal grouped Wake-on-LAN dispatcher task."""
    if not jobs_config.enabled:
        return []
    return [
        Task(
            id="tsunade.wake.dispatch",
            name="Dispatch grouped Katsuyu wake requests",
            command="jobs.wake.dispatch",
            trigger=IntervalTrigger(
                timedelta(seconds=5),
                start_at=start_at,
            ),
            metadata={
                "managed_by": "tsunade-wake",
            },
            priority=10,
        )
    ]


def attach_administration(context: AdministrationContext) -> AdministrationService:
    """Build the administration service and its listeners onto ``context.agent``."""
    administration_config = context.configuration.administration
    administration_token = _read_secret(
        administration_config.token_file, "Ohana administration token"
    )
    job_repository, worker_token = _build_jobs(context, administration_config.jobs)
    plugin_repository = PluginAdministrationRepository(
        plugin_manager=context.plugin_manager,
        scheduler=context.scheduler,
        backup_runner=lambda arguments: context.dispatcher.execute(
            "backup.run",
            arguments,
        ),
        bindings=context.plugins.administration_bindings(
            context.apply_plugin_configuration
        ),
    )
    incident_repository = _build_incident_repository(context, administration_config)
    companions = _build_companions(administration_config)
    worker_tls = _build_worker_tls(administration_config.jobs)
    investigation_executor = _build_investigation_executor(
        context, plugin_repository, job_repository
    )
    expertise_service = TsunadeExpertiseService(
        incidents=incident_repository,
        investigations=investigation_executor,
    )
    administration_service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            context.infrastructure_config_path,
        ),
        dhcp_repository=_build_dhcp_repository(administration_config.dhcp),
        plugin_repository=plugin_repository,
        network_repository=_build_network_repository(administration_config.network),
        job_repository=job_repository,
        on_infrastructure_changed=lambda changed_configuration: (
            context.agent.apply_infrastructure_configuration(
                changed_configuration,
                VisionInfrastructureMapper().to_payload(changed_configuration),
            )
        ),
        worker_ca_certificate_pem=(
            worker_tls.ca_certificate_pem if worker_tls is not None else None
        ),
        worker_ca_sha256=worker_tls.ca_sha256 if worker_tls is not None else None,
        **_wake_arguments(context, administration_config.jobs.wake_on_lan),
        incident_repository=incident_repository,
        investigation_executor=investigation_executor,
        log_source_broker=(
            LogSourceBroker(context.plugins["backup"].config, job_repository)
            if job_repository is not None
            else None
        ),
        expertise_service=expertise_service,
        automatic_read_only_investigations=True,
        **_log_analysis_arguments(context, administration_config.jobs.logs),
        companion_repository=companions.repository if companions else None,
        companion_ca_sha256=companions.ca_sha256 if companions else None,
        companion_ca_certificate_pem=(
            companions.ca_certificate_pem if companions else None
        ),
        notification_publisher=(
            companions.notifications.publish if companions else None
        ),
        repair_executors={
            # The Supervisor access is the one already used for inspection.
            "mosquitto.restart": lambda incident, target: restart_addon(
                context.plugins["backup"].config, incident.node_id, target
            ),
        },
    )
    expertise_service.set_ai_dispatcher(
        _AIJobDispatcher(job_repository, administration_service)
    )
    expertise_service.set_repair_proposer(
        lambda incident_id: administration_service.propose_incident_repair(
            str(incident_id), {}, automatic=True
        )
    )
    context.event_bus.subscribe(
        ObservationPublished,
        TsunadeObservationHandler(
            incidents=incident_repository,
            expertise=expertise_service,
            administration=administration_service,
            logs_config=administration_config.jobs.logs,
            notifications=companions.notifications if companions else None,
        ),
    )
    if (
        job_repository is not None
        and context.plugins["backup"].config.infra_01.use_katsuyu
    ):
        _enable_distributed_infra_backup(
            context, job_repository, administration_service
        )
    context.agent.administration_runtime = _build_listeners(
        administration_service,
        administration_config,
        token=administration_token,
        worker_token=worker_token,
        worker_tls=worker_tls,
        companions=companions,
    )
    return administration_service


def _read_secret(path: Path, description: str) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ValueError(f"Unable to read the {description} from {path}.") from error


def _read_certificate(path: Path, description: str) -> tuple[str, str]:
    try:
        return certificate_sha256(path)
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(
            f"Unable to read the {description} TLS CA certificate from {path}."
        ) from error


def _build_jobs(
    context: AdministrationContext,
    jobs_config: DistributedJobsConfig,
) -> tuple[DistributedJobRepository | None, str | None]:
    """Open the Katsuyu job queue and schedule its Tsunade tasks."""
    if not jobs_config.enabled:
        return None, None

    worker_token = _read_secret(jobs_config.worker_token_file, "Katsuyu worker token")
    if not worker_token:
        raise ValueError("The Katsuyu worker token cannot be empty.")

    job_repository = DistributedJobRepository(
        jobs_config.database_path,
        lease_seconds=jobs_config.lease_seconds,
        waiting_worker_after_seconds=jobs_config.waiting_worker_after_seconds,
        retention_days=jobs_config.retention_days,
        max_active_jobs=jobs_config.max_active_jobs,
        worker_available_seconds=jobs_config.wake_on_lan.available_for_seconds,
    )
    replace_plugin_tasks(
        context.scheduler,
        build_log_analysis_tasks(
            logs_config=jobs_config.logs,
            schedule_timezone=LOCAL_SCHEDULE_TIMEZONE,
        ),
        plugin_name="tsunade-logs",
    )
    replace_plugin_tasks(
        context.scheduler,
        build_wake_dispatch_tasks(
            jobs_config=jobs_config,
            start_at=context.clock.now(),
        ),
        plugin_name="tsunade-wake",
    )
    return job_repository, worker_token


def _build_network_repository(
    config: NetworkAdministrationConfig,
) -> NetworkManagerRepository | None:
    if not config.enabled:
        return None

    return NetworkManagerRepository(
        helper_path=config.helper_path,
        sudo_path=config.sudo_path,
        rollback_seconds=config.rollback_seconds,
    )


def _build_dhcp_repository(
    config: DHCPAdministrationConfig,
) -> DnsmasqDHCPRepository | None:
    if not config.enabled:
        return None

    return DnsmasqDHCPRepository(
        main_config_path=config.main_config_path,
        reservation_paths={
            "infrastructure": config.infrastructure_reservations_path,
            "servers": config.server_reservations_path,
            "network": config.network_reservations_path,
            "home_automation": config.home_automation_reservations_path,
            "critical": config.critical_reservations_path,
        },
        leases_path=config.leases_path,
        server_node_id=config.server_node_id,
        validation_command=config.validation_command,
        reload_request_path=config.reload_request_path,
    )


def _build_incident_repository(
    context: AdministrationContext,
    administration_config: AdministrationConfig,
) -> TsunadeIncidentRepository:
    repository = TsunadeIncidentRepository(administration_config.control_database_path)
    repository.reconcile_network_devices(
        {
            device.name
            for device in context.plugins["network"].config.devices
            if device.enabled
        },
        occurred_at=context.clock.now().astimezone(ZoneInfo("Europe/Paris")),
    )
    return repository


def _build_companions(
    administration_config: AdministrationConfig,
) -> _CompanionRuntime | None:
    config = administration_config.companion
    if not config.enabled:
        return None

    ca_certificate_pem, ca_sha256 = _read_certificate(
        config.ca_certificate_file, "companion"
    )
    repository = CompanionRepository(
        administration_config.control_database_path,
        credential_ttl_days=config.credential_ttl_days,
    )
    return _CompanionRuntime(
        config=config,
        repository=repository,
        ca_certificate_pem=ca_certificate_pem,
        ca_sha256=ca_sha256,
        notifications=APNsNotificationPublisher(
            config=config.push,
            companions=repository,
        ),
    )


def _build_worker_tls(jobs_config: DistributedJobsConfig) -> _WorkerTLS | None:
    if not (jobs_config.enabled and jobs_config.worker_tls.enabled):
        return None

    config = jobs_config.worker_tls
    ca_certificate_pem, ca_sha256 = _read_certificate(
        config.ca_certificate_file, "Katsuyu"
    )
    return _WorkerTLS(config, ca_certificate_pem, ca_sha256)


def _build_investigation_executor(
    context: AdministrationContext,
    plugin_repository: PluginAdministrationRepository,
    job_repository: DistributedJobRepository | None,
) -> InvestigationExecutor:
    plugins = context.plugins
    return InvestigationExecutor(
        plugins=plugin_repository,
        host_health_reader=lambda: context.host_health_monitor.collect().to_dict(),
        jobs=job_repository,
        infrastructure_reader=InfrastructureConfigurationRepository(
            context.infrastructure_config_path
        ).read,
        configuration_reader=lambda node: inspect_configuration(
            plugin_repository, plugins["backup"].config, node
        ),
        http_target_reader=lambda node: configured_http_target(
            plugins["backup"].config, node
        ),
    )


def _wake_arguments(
    context: AdministrationContext,
    wake_config: WakeOnLanConfig,
) -> dict[str, object]:
    def wake_sender(mac_address: str) -> None:
        WakeOnLanSender(
            mac_address=mac_address,
            broadcast_address=str(wake_config.broadcast_address),
            port=wake_config.port,
            burst_count=wake_config.packet_burst_count,
            burst_interval_seconds=wake_config.burst_interval_seconds,
        ).send()

    def on_wake_enabled_changed(enabled: bool) -> None:
        ConfigurationLoader.write_wake_on_lan_enabled(
            context.application_config_path,
            enabled,
        )

    return {
        "wake_timeout_seconds": wake_config.wait_timeout_seconds,
        "wake_sender": wake_sender,
        "wake_broadcast_address": str(wake_config.broadcast_address),
        "wake_port": wake_config.port,
        "wake_available_for_seconds": wake_config.available_for_seconds,
        "wake_packet_burst_count": wake_config.packet_burst_count,
        "wake_burst_interval_seconds": wake_config.burst_interval_seconds,
        "wake_retry_count": wake_config.retry_count,
        "wake_retry_delay_seconds": wake_config.retry_delay_seconds,
        "wake_batch_window_seconds": wake_config.batch_window_seconds,
        "wake_planned_window_start_hour": wake_config.planned_window_start_hour,
        "wake_planned_window_end_hour": wake_config.planned_window_end_hour,
        "wake_schedule_timezone": wake_config.schedule_timezone,
        "wake_minimum_interval_seconds": wake_config.minimum_interval_seconds,
        "wake_shutdown_after_completion": wake_config.shutdown_after_completion,
        "wake_worker_id": wake_config.worker_id,
        "wake_mac_address": wake_config.mac_address,
        "wake_enabled": wake_config.enabled,
        "on_wake_enabled_changed": on_wake_enabled_changed,
    }


def _log_analysis_arguments(
    context: AdministrationContext,
    logs_config: DistributedLogAnalysisConfig,
) -> dict[str, object]:
    def on_log_analysis_changed(
        logs_configuration: DistributedLogAnalysisConfig,
    ) -> None:
        ConfigurationLoader.write_log_analysis(
            context.application_config_path,
            logs_configuration.model_dump(mode="json"),
        )
        replace_plugin_tasks(
            context.scheduler,
            build_log_analysis_tasks(
                logs_config=logs_configuration,
                schedule_timezone=LOCAL_SCHEDULE_TIMEZONE,
            ),
            plugin_name="tsunade-logs",
        )

    return {
        "log_analysis_enabled": logs_config.enabled,
        "log_analysis_schedule": logs_config.schedule,
        "log_sources": logs_config.sources,
        "log_window_hours": logs_config.window_hours,
        "log_max_bytes": logs_config.max_bytes_per_source,
        "log_timeout_seconds": logs_config.timeout_seconds,
        "on_log_analysis_changed": on_log_analysis_changed,
    }


class _AIJobDispatcher:
    """Queue Tsunade AI inference only when a capable Katsuyu worker exists."""

    def __init__(
        self,
        job_repository: DistributedJobRepository | None,
        administration: AdministrationService,
    ) -> None:
        self._job_repository = job_repository
        self._administration = administration

    def __call__(self, payload: dict[str, object]) -> object | None:
        if self._job_repository is None or not (
            self._job_repository.has_worker_capability("ai.inference")
        ):
            return None
        return self._administration.create_job(payload)


def incident_notification(incident: Any) -> dict[str, object] | None:
    """Return the companion push for a new critical or a resolved incident."""
    if (
        incident.state == "active"
        and incident.severity == "critical"
        and incident.occurrence_count == 1
    ):
        return {
            "schema_version": 1,
            "notification_id": f"incident-{incident.incident_id}-critical",
            "type": "CRITICAL",
            "title": "Un incident critique a été détecté",
            "message": incident.message,
            "incident_id": str(incident.incident_id),
            "occurred_at": incident.started_at.isoformat(),
        }

    if incident.state == "resolved":
        repair_succeeded = any(
            repair.status == "succeeded" for repair in incident.repairs
        )
        return {
            "schema_version": 1,
            "notification_id": f"incident-{incident.incident_id}-resolved",
            "type": "RESOLVED",
            "title": (
                "La réparation demandée a réussi"
                if repair_succeeded
                else "Konoha est de nouveau sain"
            ),
            "message": incident.final_result or incident.message,
            "incident_id": str(incident.incident_id),
            "occurred_at": (incident.ended_at or incident.last_observed_at).isoformat(),
        }

    return None


class TsunadeObservationHandler:
    """Turn each observation into incidents, pushes and a first investigation."""

    def __init__(
        self,
        *,
        incidents: TsunadeIncidentRepository,
        expertise: TsunadeExpertiseService,
        administration: AdministrationService,
        logs_config: DistributedLogAnalysisConfig,
        notifications: APNsNotificationPublisher | None,
    ) -> None:
        self._incidents = incidents
        self._expertise = expertise
        self._administration = administration
        self._logs_config = logs_config
        self._notifications = notifications

    def __call__(self, event: ObservationPublished) -> None:
        incident = self._incidents.process(event.observation)
        if incident is None:
            return

        notification = incident_notification(incident)
        if notification is not None and self._notifications is not None:
            self._notifications.publish(notification)

        if incident.occurrence_count != 1:
            if self._upstream_resolved(incident):
                # The symptom outlived the upstream incident it was attached to:
                # that is new evidence, so the escalation it was spared resumes.
                self._expertise.start(incident.incident_id)
            return

        logs_config = self._logs_config
        if logs_config.enabled and incident.node_id in logs_config.sources:
            self._administration.create_job(
                _incident_log_health_job(incident, logs_config, datetime.now(UTC))
            )
            return

        self._expertise.start(incident.incident_id)

    def _upstream_resolved(self, incident: Any) -> bool:
        if incident.state != "active":
            return False
        upstream_id = correlated_upstream_id(incident)
        if upstream_id is None:
            return False
        try:
            return self._incidents.get(upstream_id).state != "active"
        except LookupError:
            return True


def _incident_log_health_job(
    incident: Any,
    logs_config: DistributedLogAnalysisConfig,
    current: datetime,
) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "job_id": str(uuid4()),
        "type": "logs.health_check",
        "created_at": current.isoformat(),
        "parameters": {
            "sources": [incident.node_id],
            "window_started_at": (current - timedelta(hours=1)).isoformat(),
            "window_ended_at": current.isoformat(),
            "max_bytes_per_source": logs_config.max_bytes_per_source,
            "baseline": [],
            "incident_id": str(incident.incident_id),
        },
        "timeout": logs_config.timeout_seconds,
    }


def _enable_distributed_infra_backup(
    context: AdministrationContext,
    job_repository: DistributedJobRepository,
    administration_service: AdministrationService,
) -> None:
    def distributed_backup_factory(
        current_backup_config: BackupConfig,
    ) -> DistributedInfraBackupCoordinator:
        transfer = DistributedInfraBackupTransfer(
            current_backup_config,
            job_repository,
        )
        administration_service.backup_transfer = transfer
        return DistributedInfraBackupCoordinator(
            current_backup_config,
            transfer,
            create_job=administration_service.create_job,
            read_job=administration_service.read_job,
        )

    administration_service.backup_transfer = context.plugins[
        "backup"
    ].plugin.enable_distributed_infra(distributed_backup_factory)


def _build_listeners(
    service: AdministrationService,
    administration_config: AdministrationConfig,
    *,
    token: str,
    worker_token: str | None,
    worker_tls: _WorkerTLS | None,
    companions: _CompanionRuntime | None,
) -> AdministrationHTTPServer | AdministrationServerGroup:
    """Loopback API, plus the TLS worker and companion listeners when enabled."""
    servers = [
        AdministrationHTTPServer(
            service=service,
            token=token,
            worker_token=worker_token,
            host=str(administration_config.host),
            port=administration_config.port,
        )
    ]
    if worker_tls is not None:
        servers.append(
            AdministrationHTTPServer(
                service=service,
                token=token,
                worker_token=None,
                host=str(worker_tls.config.host),
                port=worker_tls.config.port,
                worker_only=True,
                tls_certificate_file=worker_tls.config.certificate_file,
                tls_private_key_file=worker_tls.config.private_key_file,
            )
        )
    if companions is not None:
        servers.append(
            AdministrationHTTPServer(
                service=service,
                token=token,
                worker_token=None,
                host=str(companions.config.host),
                port=companions.config.port,
                companion_only=True,
                tls_certificate_file=companions.config.certificate_file,
                tls_private_key_file=companions.config.private_key_file,
            )
        )
    return servers[0] if len(servers) == 1 else AdministrationServerGroup(*servers)
