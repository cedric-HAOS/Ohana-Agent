"""Production bootstrap for Ohana-Agent."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from ohana_agent.api.service import AdministrationService
from ohana_agent.configuration.builders import (
    InfrastructureBuilder,
)
from ohana_agent.configuration.configuration import Configuration
from ohana_agent.configuration.enums import Environment
from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.configuration.infrastructure_validator import InfrastructureValidator
from ohana_agent.configuration.loader import ConfigurationLoader
from ohana_agent.configuration.loaders import (
    InfrastructureLoader,
)
from ohana_agent.configuration.teleinformation import TeleinformationPluginConfig
from ohana_agent.core.events import EventBus
from ohana_agent.infrastructure import InfrastructureRuntime
from ohana_agent.infrastructure.infrastructure_health_manager import (
    InfrastructureHealthManager,
)
from ohana_agent.observation import (
    InfrastructureObservationMapper,
    ObservationEngine,
    ObservationEventPublisher,
    ObservationExportHandler,
    ObservationExportPipeline,
    ObservationPublished,
    ObserverResultMapper,
    PluginObservationDispatcher,
    PluginObservationExecutor,
)
from ohana_agent.observation.events import HostHealthObserved
from ohana_agent.observation.exporters import (
    DurableVisionClient,
    HttpVisionClient,
    VisionClient,
    VisionInfrastructureMapper,
    VisionObservationExporter,
    VisionObservationMapper,
    VisionObservationOutbox,
)
from ohana_agent.observation.monitoring import MonitoringScheduleRegistry
from ohana_agent.plugins.backup.config import BackupConfig
from ohana_agent.plugins.backup.coordinator import BackupCoordinator
from ohana_agent.plugins.dhcp.check import DHCPCheck
from ohana_agent.plugins.home_assistant_telemetry.check import (
    HomeAssistantTelemetryCheck,
)
from ohana_agent.plugins.mqtt.host_health import (
    HostHealthMonitor,
    HostHealthObservationMapper,
    HostHealthReporter,
    SystemHostProbe,
)
from ohana_agent.plugins.network.check import NetworkCheck
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_manager import PluginManager
from ohana_agent.plugins.teleinformation.check import (
    TeleinformationCheck,
)
from ohana_agent.plugins.teleinformation.frame_store import (
    TeleinformationFrameStore,
)
from ohana_agent.plugins.teleinformation.ingestion import (
    TeleinformationIngestionHTTPServer,
)
from ohana_agent.plugins.wireguard.check import WireGuardCheck
from ohana_agent.plugins.zwave.check import ZWaveCheck
from ohana_agent.plugins.zwave.discovery import ZWaveDiscoveryHandler
from ohana_agent.runtime.administration_bootstrap import (
    AdministrationContext,
    attach_administration,
)
from ohana_agent.runtime.agent import ProductionAgent
from ohana_agent.runtime.plugin_catalog import (
    production_plugin_specs,
)
from ohana_agent.runtime.plugin_specs import ProductionPlugins
from ohana_agent.scheduler import (
    DispatcherTaskExecutor,
    Scheduler,
)
from ohana_agent.scheduler.clock import Clock, SystemClock

DEFAULT_PRODUCTION_OUTBOX_PATH = Path("/var/lib/ohana-agent/vision-outbox.db")


def _resolve_home_assistant_telemetry_config_path(path: Path) -> Path:
    """Use the former Shelly config when an installation has not migrated yet."""
    if path.exists():
        return path

    legacy_path = path.with_name("shelly-telemetry.yaml")
    return legacy_path if legacy_path.exists() else path


def _build_teleinformation_ingestion_runtime(
    *,
    configuration: TeleinformationPluginConfig,
    frame_store: TeleinformationFrameStore,
) -> TeleinformationIngestionHTTPServer | None:
    """Build the optional direct teleinfo2mqtt receiver."""
    if not configuration.enabled or configuration.mode != "direct_http":
        return None

    token = configuration.ingestion_token
    if token is None and configuration.ingestion_token_environment_variable:
        token = os.getenv(configuration.ingestion_token_environment_variable)
    if not token:
        source = configuration.ingestion_token_environment_variable or "configuration"
        raise ValueError(
            f"Direct Téléinformation ingestion token is missing ({source})."
        )

    return TeleinformationIngestionHTTPServer(
        frame_store=frame_store,
        token=token,
        host=configuration.listen_host,
        port=configuration.listen_port,
    )


def _build_vision_client(
    configuration: Configuration,
    vision_client: VisionClient | None,
) -> tuple[VisionClient, DurableVisionClient | None]:
    """Resolve the Ohana-Vision client, durable in production by default."""
    if vision_client is not None:
        return vision_client, None

    if not configuration.vision.enabled:
        raise ValueError(
            "Ohana-Vision export must be enabled for the production bootstrap."
        )

    http_vision_client = HttpVisionClient(
        observation_url=str(configuration.vision.observation_url),
        infrastructure_url=str(configuration.vision.infrastructure_url),
        timeout_seconds=(configuration.vision.timeout_seconds),
    )
    outbox_path = configuration.vision.outbox_path
    if (
        outbox_path is None
        and configuration.agent.environment is Environment.PRODUCTION
    ):
        outbox_path = DEFAULT_PRODUCTION_OUTBOX_PATH

    if outbox_path is None:
        return http_vision_client, None

    durable_client = DurableVisionClient(
        http_vision_client,
        VisionObservationOutbox(
            outbox_path,
            max_entries=configuration.vision.outbox_max_entries,
        ),
        retry_seconds=configuration.vision.outbox_retry_seconds,
    )
    return durable_client, durable_client


def build_production_agent(
    *,
    application_config_path: Path = Path("config/shikamaru.yaml"),
    infrastructure_config_path: Path = Path("config/infrastructure.yaml"),
    dhcp_config_path: Path = Path("config/plugins/dhcp.yaml"),
    dns_config_path: Path = Path("config/plugins/dns.yaml"),
    ntp_config_path: Path = Path("config/plugins/ntp.yaml"),
    mqtt_config_path: Path = Path("config/plugins/mqtt.yaml"),
    network_config_path: Path = Path("config/plugins/network.yaml"),
    zwave_config_path: Path = Path("config/plugins/zwave.yaml"),
    wireguard_config_path: Path = Path("config/plugins/wireguard.yaml"),
    home_assistant_telemetry_config_path: Path | None = None,
    shelly_telemetry_config_path: Path | None = None,
    teleinformation_config_path: Path = Path("config/plugins/teleinformation.yaml"),
    backup_config_path: Path = Path("config/plugins/backup.yaml"),
    vision_client: VisionClient | None = None,
    clock: Clock | None = None,
    network_check: NetworkCheck | None = None,
    dhcp_check: DHCPCheck | None = None,
    zwave_check: ZWaveCheck | None = None,
    wireguard_check: WireGuardCheck | None = None,
    home_assistant_telemetry_check: HomeAssistantTelemetryCheck | None = None,
    shelly_telemetry_check: HomeAssistantTelemetryCheck | None = None,
    teleinformation_check: TeleinformationCheck | None = None,
    backup_coordinator: BackupCoordinator | None = None,
) -> ProductionAgent:
    """Build the complete production Ohana-Agent runtime."""
    configuration = ConfigurationLoader.load(application_config_path)

    infrastructure_config = InfrastructureLoader().load(infrastructure_config_path)
    InfrastructureValidator().validate(infrastructure_config)
    infrastructure = InfrastructureBuilder().build(infrastructure_config)
    monitoring_registry = MonitoringScheduleRegistry()
    monitoring_registry.replace_from_infrastructure(infrastructure_config)
    infrastructure_runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    home_assistant_telemetry_config_path = (
        _resolve_home_assistant_telemetry_config_path(
            home_assistant_telemetry_config_path
            or shelly_telemetry_config_path
            or Path("config/plugins/home-assistant-telemetry.yaml")
        )
    )
    resolved_teleinformation_check = teleinformation_check or TeleinformationCheck()
    teleinformation_frame_store = getattr(
        resolved_teleinformation_check,
        "frame_store",
        TeleinformationFrameStore(),
    )

    event_bus = EventBus()
    resolved_vision_client, vision_export_runtime = _build_vision_client(
        configuration, vision_client
    )
    vision_observation_exporter = VisionObservationExporter(
        client=resolved_vision_client,
        mapper=VisionObservationMapper(),
    )
    plugins = ProductionPlugins.load(
        production_plugin_specs(
            dhcp_service_config=configuration.administration.dhcp,
            infrastructure_config=infrastructure_config,
            dhcp_check=dhcp_check,
            network_check=network_check,
            zwave_check=zwave_check,
            wireguard_check=wireguard_check,
            home_assistant_telemetry_check=(
                home_assistant_telemetry_check or shelly_telemetry_check
            ),
            teleinformation_check=resolved_teleinformation_check,
            backup_coordinator=backup_coordinator,
        ),
        {
            "dhcp": dhcp_config_path,
            "dns": dns_config_path,
            "ntp": ntp_config_path,
            "mqtt": mqtt_config_path,
            "network": network_config_path,
            "zwave": zwave_config_path,
            "wireguard": wireguard_config_path,
            "home_assistant_telemetry": home_assistant_telemetry_config_path,
            "teleinformation": teleinformation_config_path,
            "backup": backup_config_path,
        },
        infrastructure=infrastructure,
        infrastructure_config=infrastructure_config,
    )

    if not plugins["dns"].config.queries:
        raise ValueError(
            "The production DNS configuration must declare at least one query."
        )

    mqtt_home_assistant_publisher = plugins["mqtt"].plugin.home_assistant_publisher
    teleinformation_ingestion_runtime = _build_teleinformation_ingestion_runtime(
        configuration=plugins["teleinformation"].plugin_config,
        frame_store=teleinformation_frame_store,
    )

    host_health_observation_mapper = HostHealthObservationMapper()
    host_health_monitor = HostHealthMonitor(SystemHostProbe())
    host_health_reporter = HostHealthReporter(
        host_health_monitor,
        sinks=(
            mqtt_home_assistant_publisher.publish_host_health,
            lambda snapshot: vision_observation_exporter.export(
                host_health_observation_mapper.to_observation(snapshot)
            ),
            # Tsunade opens incidents on the Agent host (an inactive
            # ohana-vision.service, a full disk) like on any capability.
            lambda snapshot: event_bus.publish(
                HostHealthObserved(
                    host_health_observation_mapper.to_observation(snapshot)
                )
            ),
        ),
    )

    export_handler = ObservationExportHandler(
        pipeline=ObservationExportPipeline(
            exporters=[
                vision_observation_exporter,
                mqtt_home_assistant_publisher,
            ]
        )
    )

    event_bus.subscribe(
        ObservationPublished,
        export_handler.handle,
    )

    observation_engine = ObservationEngine(
        health_manager=InfrastructureHealthManager(
            runtime=infrastructure_runtime,
        ),
        mapper=InfrastructureObservationMapper(),
        result_mapper=ObserverResultMapper(),
        publisher=ObservationEventPublisher(
            event_publisher=event_bus,
        ),
    )

    plugin_context = PluginContext(
        event_bus=event_bus,
        scheduler=None,
        dispatcher=None,
        memory=None,
        capability_manager=None,
        configuration=configuration,
        runtime=infrastructure_runtime,
    )

    plugin_manager = PluginManager(
        context=plugin_context,
    )
    plugins.register(plugin_manager)

    plugin_executor = PluginObservationExecutor(
        plugin_manager=plugin_manager,
        observation_engine=observation_engine,
    )
    dispatcher = PluginObservationDispatcher(
        executor=plugin_executor,
    )

    resolved_clock = clock or SystemClock()
    administration_service: AdministrationService | None = None

    def queue_log_health_job(arguments: dict[str, object], now: datetime) -> object:
        if administration_service is None:
            raise RuntimeError("Tsunade administration is unavailable")
        return administration_service.request_log_health_check(
            now=now,
            sources=arguments["sources"],
            window_hours=int(arguments["window_hours"]),
            max_bytes=int(arguments["max_bytes_per_source"]),
            timeout_seconds=int(arguments["timeout_seconds"]),
        )

    def dispatch_due_wake_requests(now: datetime) -> None:
        if administration_service is None:
            raise RuntimeError("Tsunade administration is unavailable")
        administration_service.settle_expired_jobs(now=now)
        administration_service.dispatch_due_wake_requests(now=now)

    scheduler = Scheduler(
        clock=resolved_clock,
        executor=DispatcherTaskExecutor(
            dispatcher=dispatcher,
            monitoring_registry=monitoring_registry,
            job_runner=queue_log_health_job,
            wake_dispatcher=dispatch_due_wake_requests,
        ),
        event_bus=event_bus,
    )
    plugins.schedule(scheduler, resolved_clock.now())

    def reconfigure_infrastructure(
        changed_configuration: InfrastructureConfig,
    ) -> None:
        updated_infrastructure = InfrastructureBuilder().build(changed_configuration)
        updated_runtime = InfrastructureRuntime.from_infrastructure(
            updated_infrastructure
        )

        def swap_runtime() -> None:
            observation_engine.health_manager.runtime = updated_runtime

        plugins.reconfigure_infrastructure(
            updated_infrastructure,
            changed_configuration,
            scheduler=scheduler,
            now=resolved_clock.now(),
            before_commit=swap_runtime,
        )
        monitoring_registry.replace_from_infrastructure(changed_configuration)

    def replace_teleinformation_ingestion(
        _: object,
        plugin_config: TeleinformationPluginConfig,
    ) -> None:
        agent.replace_teleinformation_ingestion_runtime(
            _build_teleinformation_ingestion_runtime(
                configuration=plugin_config,
                frame_store=teleinformation_frame_store,
            )
        )

    def update_log_source_broker(backup_config: BackupConfig, _: object) -> None:
        if (
            administration_service is not None
            and administration_service.log_source_broker is not None
        ):
            administration_service.log_source_broker.config = backup_config

    plugins.on_applied("teleinformation", replace_teleinformation_ingestion)
    plugins.on_applied("backup", update_log_source_broker)

    def apply_plugin_configuration(identifier: str, plugin_config: object) -> None:
        agent.apply_plugin_configuration(
            lambda: plugins.apply(
                identifier,
                plugin_config,
                scheduler=scheduler,
                now=resolved_clock.now(),
            )
        )

    agent = ProductionAgent(
        scheduler=scheduler,
        vision_client=resolved_vision_client,
        infrastructure_payload=(
            VisionInfrastructureMapper().to_payload(infrastructure_config)
        ),
        infrastructure_retry_seconds=(
            configuration.vision.infrastructure_retry_seconds
        ),
        infrastructure_refresh_seconds=(
            configuration.vision.infrastructure_refresh_seconds
        ),
        infrastructure_reconfigure=reconfigure_infrastructure,
        teleinformation_ingestion_runtime=teleinformation_ingestion_runtime,
        home_assistant_publisher=mqtt_home_assistant_publisher,
        host_health_runtime=host_health_reporter,
        vision_export_runtime=vision_export_runtime,
    )

    zwave_discovery_handler = ZWaveDiscoveryHandler(
        observation_engine=observation_engine,
        infrastructure_payload=lambda: agent.infrastructure_payload,
        update_infrastructure=agent.update_infrastructure_payload,
    )
    event_bus.subscribe(
        ObservationPublished,
        zwave_discovery_handler.handle,
    )

    if configuration.administration.enabled:
        administration_service = attach_administration(
            AdministrationContext(
                configuration=configuration,
                application_config_path=application_config_path,
                infrastructure_config_path=infrastructure_config_path,
                plugins=plugins,
                plugin_manager=plugin_manager,
                scheduler=scheduler,
                dispatcher=dispatcher,
                event_bus=event_bus,
                host_health_monitor=host_health_monitor,
                clock=resolved_clock,
                agent=agent,
                apply_plugin_configuration=apply_plugin_configuration,
            )
        )

    return agent
