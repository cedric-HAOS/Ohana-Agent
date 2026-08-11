"""Production bootstrap for Ohana-Agent."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from administration import (
    AdministrationHTTPServer,
    AdministrationService,
    DnsmasqDHCPRepository,
    InfrastructureConfigurationRepository,
    NetworkManagerRepository,
    PluginAdministrationBinding,
    PluginAdministrationRepository,
)
from builder import (
    BackupConfigurationBuilder,
    DHCPConfigurationBuilder,
    DNSConfigurationBuilder,
    HomeAssistantTelemetryConfigurationBuilder,
    InfrastructureBuilder,
    MQTTConfigurationBuilder,
    NetworkConfigurationBuilder,
    NTPConfigurationBuilder,
    TeleinformationConfigurationBuilder,
    WireGuardConfigurationBuilder,
    ZWaveConfigurationBuilder,
)
from configuration.backup import BackupPluginConfig
from configuration.dhcp import DHCPPluginConfig
from configuration.dns import DNSPluginConfig
from configuration.enums import Environment
from configuration.home_assistant_telemetry import (
    HomeAssistantTelemetryPluginConfig,
)
from configuration.infrastructure import InfrastructureConfig
from configuration.infrastructure_validator import InfrastructureValidator
from configuration.loader import ConfigurationLoader
from configuration.mqtt_plugin import MQTTPluginConfig
from configuration.network import NetworkPluginConfig
from configuration.ntp import NTPPluginConfig
from configuration.teleinformation import TeleinformationPluginConfig
from configuration.wireguard import WireGuardPluginConfig
from configuration.zwave import ZWavePluginConfig
from core.events import EventBus
from infrastructure import InfrastructureRuntime
from infrastructure.infrastructure_health_manager import (
    InfrastructureHealthManager,
)
from loader import (
    BackupConfigLoader,
    DHCPConfigLoader,
    DNSConfigLoader,
    HomeAssistantTelemetryConfigLoader,
    InfrastructureLoader,
    MQTTConfigLoader,
    NetworkConfigLoader,
    NTPConfigLoader,
    TeleinformationConfigLoader,
    WireGuardConfigLoader,
    ZWaveConfigLoader,
)
from monitoring import MonitoringScheduleRegistry
from observer import (
    InfrastructureObservationMapper,
    ObservationEngine,
    ObservationEventPublisher,
    ObservationExportHandler,
    ObservationExportPipeline,
    ObservationPublished,
    ObserverResult,
    ObserverResultMapper,
    PluginObservationDispatcher,
    PluginObservationExecutor,
)
from observer.exporters import (
    DurableVisionClient,
    HttpVisionClient,
    VisionClient,
    VisionInfrastructureMapper,
    VisionObservationExporter,
    VisionObservationMapper,
    VisionObservationOutbox,
)
from plugin.plugin_context import PluginContext
from plugin.plugin_manager import PluginManager
from plugins.backup.backup_config import BackupConfig
from plugins.backup.backup_coordinator import BackupCoordinator
from plugins.backup.backup_plugin import BackupPlugin
from plugins.dhcp.dhcp_check import DHCPCheck
from plugins.dhcp.dhcp_config import DHCPConfig
from plugins.dhcp.dhcp_plugin import DHCPPlugin
from plugins.dns.dns_check import DNSCheck
from plugins.dns.dns_config import DNSConfig
from plugins.dns.dns_plugin import DNSPlugin
from plugins.home_assistant_telemetry.home_assistant_telemetry_check import (
    HomeAssistantTelemetryCheck,
)
from plugins.home_assistant_telemetry.home_assistant_telemetry_config import (
    HomeAssistantTelemetryConfig,
)
from plugins.home_assistant_telemetry.home_assistant_telemetry_plugin import (
    HomeAssistantTelemetryPlugin,
)
from plugins.mqtt.home_assistant_publisher import MQTTHomeAssistantPublisher
from plugins.mqtt.host_health import (
    HostHealthMonitor,
    HostHealthObservationMapper,
    HostHealthReporter,
    SystemHostProbe,
)
from plugins.mqtt.mqtt_check import MQTTCheck
from plugins.mqtt.mqtt_config import MQTTConfig
from plugins.mqtt.mqtt_plugin import MQTTPlugin
from plugins.network.network_check import NetworkCheck
from plugins.network.network_config import NetworkConfig
from plugins.network.network_plugin import NetworkPlugin
from plugins.ntp.ntp_check import NTPCheck
from plugins.ntp.ntp_config import NTPConfig
from plugins.ntp.ntp_plugin import NTPPlugin
from plugins.teleinformation.teleinformation_check import TeleinformationCheck
from plugins.teleinformation.teleinformation_config import TeleinformationConfig
from plugins.teleinformation.teleinformation_frame_store import (
    TeleinformationFrameStore,
)
from plugins.teleinformation.teleinformation_ingestion import (
    TeleinformationIngestionHTTPServer,
)
from plugins.teleinformation.teleinformation_plugin import TeleinformationPlugin
from plugins.wireguard.wireguard_check import WireGuardCheck
from plugins.wireguard.wireguard_config import WireGuardConfig
from plugins.wireguard.wireguard_plugin import WireGuardPlugin
from plugins.zwave.zwave_check import ZWaveCheck
from plugins.zwave.zwave_config import ZWaveConfig
from plugins.zwave.zwave_discovery import ZWaveDiscoveryHandler
from plugins.zwave.zwave_plugin import ZWavePlugin
from production_agent import ProductionAgent
from scheduler import (
    CronTrigger,
    DispatcherTaskExecutor,
    IntervalTrigger,
    Scheduler,
    Task,
)
from scheduler.clock import Clock, SystemClock

DEFAULT_PRODUCTION_OUTBOX_PATH = Path("/var/lib/ohana-agent/vision-outbox.db")


def _build_dhcp_tasks(
    *,
    dhcp_config: DHCPConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled status observation per DHCP service."""
    return [
        Task(
            id=f"dhcp.status:{server.name}",
            name=f"Observe DHCP service {server.name}",
            command="dhcp.status",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "server": server.address,
                "port": server.port,
                "service_id": server.name,
            },
            metadata={
                "managed_by": "dhcp",
                "node_id": server.node_id,
                "service_id": server.name,
                "server": server.address,
                "port": server.port,
            },
        )
        for server in dhcp_config.servers
        if server.enabled
    ]


def _build_dns_tasks(
    *,
    dns_config: DNSConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled observation per DNS service and query."""
    tasks: list[Task] = []

    for server in dns_config.servers:
        if not server.enabled:
            continue

        for query_index, hostname in enumerate(dns_config.queries):
            tasks.append(
                Task(
                    id=(f"dns.resolve:{server.name}:{query_index}:{hostname}"),
                    name=(f"Resolve {hostname} through {server.name}"),
                    command="dns.resolve",
                    trigger=IntervalTrigger(
                        interval=timedelta(seconds=interval_seconds),
                        start_at=start_at,
                    ),
                    arguments={
                        "hostname": hostname,
                        "server": server.address,
                        "service_id": server.name,
                    },
                    metadata={
                        "managed_by": "dns",
                        "node_id": server.node_id,
                        "service_id": server.name,
                        "server": server.address,
                    },
                )
            )

    return tasks


def _build_ntp_tasks(
    *,
    ntp_config: NTPConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled observation per enabled NTP service."""
    return [
        Task(
            id=f"ntp.query:{server.name}",
            name=f"Query time through {server.name}",
            command="ntp.query",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "server": server.address,
                "port": server.port,
                "service_id": server.name,
            },
            metadata={
                "managed_by": "ntp",
                "node_id": server.node_id,
                "service_id": server.name,
                "server": server.address,
                "port": server.port,
            },
        )
        for server in ntp_config.servers
        if server.enabled
    ]


def _build_mqtt_tasks(
    *,
    mqtt_config: MQTTConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled round-trip observation per enabled MQTT broker."""
    return [
        Task(
            id=f"mqtt.roundtrip:{broker.name}",
            name=f"Test MQTT round trip through {broker.name}",
            command="mqtt.roundtrip",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "broker": broker.address,
                "port": broker.port,
                "service_id": broker.name,
            },
            metadata={
                "managed_by": "mqtt",
                "node_id": broker.node_id,
                "service_id": broker.name,
                "broker": broker.address,
                "port": broker.port,
            },
        )
        for broker in mqtt_config.brokers
        if broker.enabled
    ]


def _build_network_tasks(
    *,
    network_config: NetworkConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build presence observations spread evenly across one interval."""
    devices = [device for device in network_config.devices if device.enabled]

    if not devices:
        return []

    spacing_seconds = interval_seconds / len(devices)

    return [
        Task(
            id=f"network.reachable:{device.name}",
            name=f"Check network presence of {device.label}",
            command="network.reachable",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at + timedelta(seconds=device_index * spacing_seconds),
            ),
            arguments={
                "address": device.address,
                "device_id": device.name,
                "label": device.label,
                "node_id": device.node_id,
            },
            metadata={
                "managed_by": "network",
                "node_id": device.node_id or device.name,
                "device_id": device.name,
                "address": device.address,
            },
        )
        for device_index, device in enumerate(devices)
    ]


def _build_zwave_tasks(
    *,
    zwave_config: ZWaveConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled health observation per Z-Wave service."""
    return [
        Task(
            id=f"zwave.status:{service.name}",
            name=f"Check Z-Wave controller {service.name}",
            command="zwave.status",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "url": service.url,
                "service_id": service.name,
            },
            metadata={
                "managed_by": "zwave",
                "node_id": service.node_id,
                "service_id": service.name,
                "url": service.url,
            },
        )
        for service in zwave_config.services
        if service.enabled
    ]


def _build_wireguard_tasks(
    *,
    wireguard_config: WireGuardConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled inspection per Freebox WireGuard service."""
    return [
        Task(
            id=f"wireguard.status:{service.name}",
            name=f"Inspect Freebox WireGuard service {service.name}",
            command="wireguard.status",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "base_url": service.base_url,
                "server_name": service.server_name,
                "service_id": service.name,
            },
            metadata={
                "managed_by": "wireguard",
                "node_id": service.node_id,
                "service_id": service.name,
                "base_url": service.base_url,
                "server_name": service.server_name,
            },
        )
        for service in wireguard_config.services
        if service.enabled
    ]


def _build_home_assistant_telemetry_tasks(
    *,
    home_assistant_telemetry_config: HomeAssistantTelemetryConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one telemetry freshness observation per declared service."""
    return [
        Task(
            id=f"home_assistant.telemetry.freshness:{service.name}",
            name=f"Check Home Assistant telemetry service {service.name}",
            command="home_assistant_telemetry.freshness",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "service_id": service.name,
                "service_name": service.label,
                "node_id": service.node_id,
                "primary_entity_id": service.primary_entity_id,
                "secondary_entity_id": service.secondary_entity_id,
                "maximum_age_seconds": service.maximum_age_seconds,
            },
            metadata={
                "managed_by": "home_assistant_telemetry",
                "service_id": service.name,
                "service_name": service.label,
                "node_id": service.node_id,
                "primary_entity_id": service.primary_entity_id,
                "secondary_entity_id": service.secondary_entity_id,
                "maximum_age_seconds": service.maximum_age_seconds,
            },
        )
        for service in home_assistant_telemetry_config.services
        if service.enabled
    ]


def _build_teleinformation_tasks(
    *,
    teleinformation_config: TeleinformationConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one Linky Téléinformation observation per declared service."""
    return [
        Task(
            id=f"teleinformation.freshness:{service.name}",
            name=f"Check Linky teleinformation service {service.name}",
            command="teleinformation.freshness",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "service_id": service.name,
                "service_name": service.label,
                "node_id": service.node_id,
                "source_id": service.source_id,
                "meter_id": service.meter_id,
                "apparent_power_entity_id": service.apparent_power_entity_id,
                "tariff_entity_id": service.tariff_entity_id,
                "blue_off_peak_entity_id": service.blue_off_peak_entity_id,
                "blue_peak_entity_id": service.blue_peak_entity_id,
                "white_off_peak_entity_id": service.white_off_peak_entity_id,
                "white_peak_entity_id": service.white_peak_entity_id,
                "red_off_peak_entity_id": service.red_off_peak_entity_id,
                "red_peak_entity_id": service.red_peak_entity_id,
                "maximum_age_seconds": service.maximum_age_seconds,
            },
            metadata={
                "managed_by": "teleinformation",
                "service_id": service.name,
                "service_name": service.label,
                "node_id": service.node_id,
                "source_id": service.source_id,
                "meter_id": service.meter_id,
                "apparent_power_entity_id": service.apparent_power_entity_id,
                "tariff_entity_id": service.tariff_entity_id,
                "maximum_age_seconds": service.maximum_age_seconds,
            },
        )
        for service in teleinformation_config.services
        if service.enabled
    ]


def _build_backup_tasks(*, backup_config: BackupConfig) -> list[Task]:
    """Build one independent daily HAOS backup task per configured target."""
    return [
        Task(
            id=f"backup.run:{target.id}",
            name=f"Back up {target.label}",
            command="backup.run",
            trigger=CronTrigger(target.schedule),
            arguments={
                "target_id": target.id,
                "device_id": target.id,
                "node_id": target.id,
            },
            metadata={
                "managed_by": "backup",
                "target_id": target.id,
                "device_id": target.id,
                "schedule": target.schedule,
            },
        )
        for target in backup_config.targets
        if target.enabled
    ]


def _replace_plugin_tasks(
    scheduler: Scheduler,
    tasks: list[Task],
    *,
    plugin_name: str,
) -> None:
    """Atomically replace scheduler tasks managed by one plugin."""
    for task in scheduler.list_tasks():
        if (
            task.command.startswith(f"{plugin_name}.")
            or task.metadata.get("managed_by") == plugin_name
        ):
            scheduler.remove_task(task.id)

    for task in tasks:
        scheduler.add_task(task)


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
    dhcp_service_config = configuration.administration.dhcp

    infrastructure_config = InfrastructureLoader().load(infrastructure_config_path)
    InfrastructureValidator().validate(infrastructure_config)
    infrastructure = InfrastructureBuilder().build(infrastructure_config)
    current_infrastructure = infrastructure
    current_infrastructure_config = infrastructure_config
    monitoring_registry = MonitoringScheduleRegistry()
    monitoring_registry.replace_from_infrastructure(infrastructure_config)
    infrastructure_runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    dhcp_plugin_config = DHCPConfigLoader().load(dhcp_config_path)
    dhcp_config = DHCPConfigurationBuilder().build(
        infrastructure,
        dhcp_plugin_config,
        server_node_id=dhcp_service_config.server_node_id,
        main_config_path=dhcp_service_config.main_config_path,
        leases_path=dhcp_service_config.leases_path,
    )

    dns_plugin_config = DNSConfigLoader().load(dns_config_path)
    dns_config = DNSConfigurationBuilder().build(
        infrastructure,
        dns_plugin_config,
    )

    if not dns_config.queries:
        raise ValueError(
            "The production DNS configuration must declare at least one query."
        )

    ntp_plugin_config = NTPConfigLoader().load(ntp_config_path)
    ntp_config = NTPConfigurationBuilder().build(
        infrastructure,
        ntp_plugin_config,
    )

    mqtt_plugin_config = MQTTConfigLoader().load(mqtt_config_path)
    mqtt_config = MQTTConfigurationBuilder().build(
        infrastructure,
        mqtt_plugin_config,
    )

    network_plugin_config = NetworkConfigLoader().load(network_config_path)
    network_config = NetworkConfigurationBuilder().build(
        infrastructure_config,
        network_plugin_config,
    )

    zwave_plugin_config = ZWaveConfigLoader().load(zwave_config_path)
    zwave_config = ZWaveConfigurationBuilder().build(
        infrastructure,
        zwave_plugin_config,
    )

    wireguard_plugin_config = WireGuardConfigLoader().load(wireguard_config_path)
    wireguard_config = WireGuardConfigurationBuilder().build(
        infrastructure,
        wireguard_plugin_config,
    )

    requested_home_assistant_telemetry_path = (
        home_assistant_telemetry_config_path
        or shelly_telemetry_config_path
        or Path("config/plugins/home-assistant-telemetry.yaml")
    )
    home_assistant_telemetry_config_path = (
        _resolve_home_assistant_telemetry_config_path(
            requested_home_assistant_telemetry_path
        )
    )
    home_assistant_telemetry_plugin_config = HomeAssistantTelemetryConfigLoader().load(
        home_assistant_telemetry_config_path
    )
    home_assistant_telemetry_config = (
        HomeAssistantTelemetryConfigurationBuilder().build(
            infrastructure,
            home_assistant_telemetry_plugin_config,
        )
    )

    teleinformation_plugin_config = TeleinformationConfigLoader().load(
        teleinformation_config_path
    )
    teleinformation_config = TeleinformationConfigurationBuilder().build(
        infrastructure,
        teleinformation_plugin_config,
    )
    backup_plugin_config = BackupConfigLoader().load(backup_config_path)
    backup_config = BackupConfigurationBuilder().build(backup_plugin_config)
    resolved_teleinformation_check = teleinformation_check or TeleinformationCheck()
    teleinformation_frame_store = getattr(
        resolved_teleinformation_check,
        "frame_store",
        TeleinformationFrameStore(),
    )
    teleinformation_ingestion_runtime = _build_teleinformation_ingestion_runtime(
        configuration=teleinformation_plugin_config,
        frame_store=teleinformation_frame_store,
    )

    event_bus = EventBus()

    resolved_vision_client = vision_client
    vision_export_runtime: DurableVisionClient | None = None

    if resolved_vision_client is None:
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
            resolved_vision_client = http_vision_client
        else:
            vision_export_runtime = DurableVisionClient(
                http_vision_client,
                VisionObservationOutbox(outbox_path),
                retry_seconds=configuration.vision.outbox_retry_seconds,
            )
            resolved_vision_client = vision_export_runtime

    vision_observation_exporter = VisionObservationExporter(
        client=resolved_vision_client,
        mapper=VisionObservationMapper(),
    )
    mqtt_home_assistant_publisher = MQTTHomeAssistantPublisher(
        config=mqtt_config,
        infrastructure=infrastructure_config,
    )
    host_health_observation_mapper = HostHealthObservationMapper()
    host_health_reporter = HostHealthReporter(
        HostHealthMonitor(SystemHostProbe()),
        sinks=(
            mqtt_home_assistant_publisher.publish_host_health,
            lambda snapshot: vision_observation_exporter.export(
                host_health_observation_mapper.to_observation(snapshot)
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

    dhcp_plugin = DHCPPlugin(
        check=dhcp_check or DHCPCheck(),
        config=dhcp_config,
    )
    plugin_manager.register(dhcp_plugin)

    dns_plugin = DNSPlugin(
        check=DNSCheck(),
        config=dns_config,
    )
    plugin_manager.register(dns_plugin)

    ntp_plugin = NTPPlugin(
        check=NTPCheck(),
        config=ntp_config,
    )
    plugin_manager.register(ntp_plugin)

    mqtt_plugin = MQTTPlugin(
        check=MQTTCheck(),
        config=mqtt_config,
        home_assistant_publisher=mqtt_home_assistant_publisher,
    )
    plugin_manager.register(mqtt_plugin)

    network_plugin = NetworkPlugin(
        check=network_check or NetworkCheck(),
        config=network_config,
    )
    plugin_manager.register(network_plugin)

    zwave_plugin = ZWavePlugin(
        check=zwave_check or ZWaveCheck(),
        config=zwave_config,
    )
    plugin_manager.register(zwave_plugin)

    wireguard_plugin = WireGuardPlugin(
        check=wireguard_check or WireGuardCheck(),
        config=wireguard_config,
    )
    plugin_manager.register(wireguard_plugin)

    home_assistant_telemetry_plugin = HomeAssistantTelemetryPlugin(
        check=(
            home_assistant_telemetry_check
            or shelly_telemetry_check
            or HomeAssistantTelemetryCheck()
        ),
        config=home_assistant_telemetry_config,
    )
    plugin_manager.register(home_assistant_telemetry_plugin)

    teleinformation_plugin = TeleinformationPlugin(
        check=resolved_teleinformation_check,
        config=teleinformation_config,
    )
    plugin_manager.register(teleinformation_plugin)

    backup_plugin = BackupPlugin(
        config=backup_config,
        coordinator=backup_coordinator,
    )
    plugin_manager.register(backup_plugin)

    plugin_executor = PluginObservationExecutor(
        plugin_manager=plugin_manager,
        observation_engine=observation_engine,
    )
    dispatcher = PluginObservationDispatcher(
        executor=plugin_executor,
    )

    resolved_clock = clock or SystemClock()

    scheduler = Scheduler(
        clock=resolved_clock,
        executor=DispatcherTaskExecutor(
            dispatcher=dispatcher,
            monitoring_registry=monitoring_registry,
        ),
        event_bus=event_bus,
    )

    _replace_plugin_tasks(
        scheduler,
        (
            _build_dhcp_tasks(
                dhcp_config=dhcp_config,
                interval_seconds=dhcp_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if dhcp_plugin_config.enabled
            else []
        ),
        plugin_name="dhcp",
    )
    _replace_plugin_tasks(
        scheduler,
        (
            _build_dns_tasks(
                dns_config=dns_config,
                interval_seconds=dns_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if dns_plugin_config.enabled
            else []
        ),
        plugin_name="dns",
    )
    _replace_plugin_tasks(
        scheduler,
        (
            _build_ntp_tasks(
                ntp_config=ntp_config,
                interval_seconds=ntp_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if ntp_plugin_config.enabled
            else []
        ),
        plugin_name="ntp",
    )
    _replace_plugin_tasks(
        scheduler,
        (
            _build_mqtt_tasks(
                mqtt_config=mqtt_config,
                interval_seconds=mqtt_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if mqtt_plugin_config.enabled
            else []
        ),
        plugin_name="mqtt",
    )
    _replace_plugin_tasks(
        scheduler,
        (
            _build_network_tasks(
                network_config=network_config,
                interval_seconds=network_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if network_plugin_config.enabled
            else []
        ),
        plugin_name="network",
    )
    _replace_plugin_tasks(
        scheduler,
        (
            _build_zwave_tasks(
                zwave_config=zwave_config,
                interval_seconds=zwave_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if zwave_plugin_config.enabled
            else []
        ),
        plugin_name="zwave",
    )
    _replace_plugin_tasks(
        scheduler,
        (
            _build_wireguard_tasks(
                wireguard_config=wireguard_config,
                interval_seconds=wireguard_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if wireguard_plugin_config.enabled
            else []
        ),
        plugin_name="wireguard",
    )
    _replace_plugin_tasks(
        scheduler,
        (
            _build_home_assistant_telemetry_tasks(
                home_assistant_telemetry_config=home_assistant_telemetry_config,
                interval_seconds=(
                    home_assistant_telemetry_plugin_config.interval_seconds
                ),
                start_at=resolved_clock.now(),
            )
            if home_assistant_telemetry_plugin_config.enabled
            else []
        ),
        plugin_name="home_assistant_telemetry",
    )
    _replace_plugin_tasks(
        scheduler,
        (
            _build_teleinformation_tasks(
                teleinformation_config=teleinformation_config,
                interval_seconds=teleinformation_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if teleinformation_plugin_config.enabled
            else []
        ),
        plugin_name="teleinformation",
    )
    _replace_plugin_tasks(
        scheduler,
        _build_backup_tasks(backup_config=backup_config)
        if backup_plugin_config.enabled
        else [],
        plugin_name="backup",
    )

    def reconfigure_infrastructure(
        changed_configuration: InfrastructureConfig,
    ) -> None:
        nonlocal current_infrastructure, current_infrastructure_config

        updated_infrastructure = InfrastructureBuilder().build(changed_configuration)
        updated_runtime = InfrastructureRuntime.from_infrastructure(
            updated_infrastructure
        )
        updated_dhcp_config = DHCPConfigurationBuilder().build(
            updated_infrastructure,
            dhcp_plugin_config,
            server_node_id=dhcp_service_config.server_node_id,
            main_config_path=dhcp_service_config.main_config_path,
            leases_path=dhcp_service_config.leases_path,
        )
        updated_dns_config = DNSConfigurationBuilder().build(
            updated_infrastructure,
            dns_plugin_config,
        )
        updated_ntp_config = NTPConfigurationBuilder().build(
            updated_infrastructure,
            ntp_plugin_config,
        )
        updated_mqtt_config = MQTTConfigurationBuilder().build(
            updated_infrastructure,
            mqtt_plugin_config,
        )
        updated_network_config = NetworkConfigurationBuilder().build(
            changed_configuration,
            network_plugin_config,
        )
        updated_zwave_config = ZWaveConfigurationBuilder().build(
            updated_infrastructure,
            zwave_plugin_config,
        )
        updated_wireguard_config = WireGuardConfigurationBuilder().build(
            updated_infrastructure,
            wireguard_plugin_config,
        )
        updated_home_assistant_telemetry_config = (
            HomeAssistantTelemetryConfigurationBuilder().build(
                updated_infrastructure,
                home_assistant_telemetry_plugin_config,
            )
        )
        updated_teleinformation_config = TeleinformationConfigurationBuilder().build(
            updated_infrastructure,
            teleinformation_plugin_config,
        )
        updated_dhcp_tasks = (
            _build_dhcp_tasks(
                dhcp_config=updated_dhcp_config,
                interval_seconds=dhcp_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if dhcp_plugin_config.enabled
            else []
        )
        updated_dns_tasks = (
            _build_dns_tasks(
                dns_config=updated_dns_config,
                interval_seconds=dns_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if dns_plugin_config.enabled
            else []
        )
        updated_ntp_tasks = (
            _build_ntp_tasks(
                ntp_config=updated_ntp_config,
                interval_seconds=ntp_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if ntp_plugin_config.enabled
            else []
        )
        updated_mqtt_tasks = (
            _build_mqtt_tasks(
                mqtt_config=updated_mqtt_config,
                interval_seconds=mqtt_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if mqtt_plugin_config.enabled
            else []
        )
        updated_network_tasks = (
            _build_network_tasks(
                network_config=updated_network_config,
                interval_seconds=network_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if network_plugin_config.enabled
            else []
        )
        updated_zwave_tasks = (
            _build_zwave_tasks(
                zwave_config=updated_zwave_config,
                interval_seconds=zwave_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if zwave_plugin_config.enabled
            else []
        )
        updated_wireguard_tasks = (
            _build_wireguard_tasks(
                wireguard_config=updated_wireguard_config,
                interval_seconds=wireguard_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if wireguard_plugin_config.enabled
            else []
        )
        updated_home_assistant_telemetry_tasks = (
            _build_home_assistant_telemetry_tasks(
                home_assistant_telemetry_config=updated_home_assistant_telemetry_config,
                interval_seconds=home_assistant_telemetry_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if home_assistant_telemetry_plugin_config.enabled
            else []
        )
        updated_teleinformation_tasks = (
            _build_teleinformation_tasks(
                teleinformation_config=updated_teleinformation_config,
                interval_seconds=teleinformation_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if teleinformation_plugin_config.enabled
            else []
        )

        observation_engine.health_manager.runtime = updated_runtime
        dhcp_plugin.reconfigure(updated_dhcp_config)
        dns_plugin.reconfigure(updated_dns_config)
        ntp_plugin.reconfigure(updated_ntp_config)
        mqtt_plugin.reconfigure(
            updated_mqtt_config,
            infrastructure=changed_configuration,
        )
        network_plugin.reconfigure(updated_network_config)
        zwave_plugin.reconfigure(updated_zwave_config)
        wireguard_plugin.reconfigure(updated_wireguard_config)
        home_assistant_telemetry_plugin.reconfigure(
            updated_home_assistant_telemetry_config
        )
        teleinformation_plugin.reconfigure(updated_teleinformation_config)
        _replace_plugin_tasks(
            scheduler,
            updated_dhcp_tasks,
            plugin_name="dhcp",
        )
        _replace_plugin_tasks(
            scheduler,
            updated_dns_tasks,
            plugin_name="dns",
        )
        _replace_plugin_tasks(
            scheduler,
            updated_ntp_tasks,
            plugin_name="ntp",
        )
        _replace_plugin_tasks(
            scheduler,
            updated_mqtt_tasks,
            plugin_name="mqtt",
        )
        _replace_plugin_tasks(
            scheduler,
            updated_network_tasks,
            plugin_name="network",
        )
        _replace_plugin_tasks(
            scheduler,
            updated_zwave_tasks,
            plugin_name="zwave",
        )
        _replace_plugin_tasks(
            scheduler,
            updated_wireguard_tasks,
            plugin_name="wireguard",
        )
        _replace_plugin_tasks(
            scheduler,
            updated_home_assistant_telemetry_tasks,
            plugin_name="home_assistant_telemetry",
        )
        _replace_plugin_tasks(
            scheduler,
            updated_teleinformation_tasks,
            plugin_name="teleinformation",
        )
        monitoring_registry.replace_from_infrastructure(changed_configuration)
        current_infrastructure = updated_infrastructure
        current_infrastructure_config = changed_configuration

    def apply_dhcp_configuration(configuration: DHCPPluginConfig) -> None:
        nonlocal dhcp_plugin_config

        updated_config = DHCPConfigurationBuilder().build(
            current_infrastructure,
            configuration,
            server_node_id=dhcp_service_config.server_node_id,
            main_config_path=dhcp_service_config.main_config_path,
            leases_path=dhcp_service_config.leases_path,
        )
        dhcp_plugin.reconfigure(updated_config)
        _replace_plugin_tasks(
            scheduler,
            (
                _build_dhcp_tasks(
                    dhcp_config=updated_config,
                    interval_seconds=configuration.interval_seconds,
                    start_at=resolved_clock.now(),
                )
                if configuration.enabled
                else []
            ),
            plugin_name="dhcp",
        )
        dhcp_plugin_config = configuration

    def apply_dns_configuration(configuration: DNSPluginConfig) -> None:
        nonlocal dns_plugin_config

        updated_config = DNSConfigurationBuilder().build(
            current_infrastructure,
            configuration,
        )
        dns_plugin.reconfigure(updated_config)
        _replace_plugin_tasks(
            scheduler,
            (
                _build_dns_tasks(
                    dns_config=updated_config,
                    interval_seconds=configuration.interval_seconds,
                    start_at=resolved_clock.now(),
                )
                if configuration.enabled
                else []
            ),
            plugin_name="dns",
        )
        dns_plugin_config = configuration

    def apply_ntp_configuration(configuration: NTPPluginConfig) -> None:
        nonlocal ntp_plugin_config

        updated_config = NTPConfigurationBuilder().build(
            current_infrastructure,
            configuration,
        )
        ntp_plugin.reconfigure(updated_config)
        _replace_plugin_tasks(
            scheduler,
            (
                _build_ntp_tasks(
                    ntp_config=updated_config,
                    interval_seconds=configuration.interval_seconds,
                    start_at=resolved_clock.now(),
                )
                if configuration.enabled
                else []
            ),
            plugin_name="ntp",
        )
        ntp_plugin_config = configuration

    def apply_mqtt_configuration(configuration: MQTTPluginConfig) -> None:
        nonlocal mqtt_plugin_config

        updated_config = MQTTConfigurationBuilder().build(
            current_infrastructure,
            configuration,
        )
        mqtt_plugin.reconfigure(updated_config)
        _replace_plugin_tasks(
            scheduler,
            (
                _build_mqtt_tasks(
                    mqtt_config=updated_config,
                    interval_seconds=configuration.interval_seconds,
                    start_at=resolved_clock.now(),
                )
                if configuration.enabled
                else []
            ),
            plugin_name="mqtt",
        )
        mqtt_plugin_config = configuration

    def apply_network_configuration(configuration: NetworkPluginConfig) -> None:
        nonlocal network_plugin_config

        updated_config = NetworkConfigurationBuilder().build(
            current_infrastructure_config,
            configuration,
        )
        network_plugin.reconfigure(updated_config)
        _replace_plugin_tasks(
            scheduler,
            (
                _build_network_tasks(
                    network_config=updated_config,
                    interval_seconds=configuration.interval_seconds,
                    start_at=resolved_clock.now(),
                )
                if configuration.enabled
                else []
            ),
            plugin_name="network",
        )
        network_plugin_config = configuration

    def apply_zwave_configuration(configuration: ZWavePluginConfig) -> None:
        nonlocal zwave_plugin_config

        updated_config = ZWaveConfigurationBuilder().build(
            current_infrastructure,
            configuration,
        )
        zwave_plugin.reconfigure(updated_config)
        _replace_plugin_tasks(
            scheduler,
            (
                _build_zwave_tasks(
                    zwave_config=updated_config,
                    interval_seconds=configuration.interval_seconds,
                    start_at=resolved_clock.now(),
                )
                if configuration.enabled
                else []
            ),
            plugin_name="zwave",
        )
        zwave_plugin_config = configuration

    def apply_wireguard_configuration(
        configuration: WireGuardPluginConfig,
    ) -> None:
        nonlocal wireguard_plugin_config

        updated_config = WireGuardConfigurationBuilder().build(
            current_infrastructure,
            configuration,
        )
        wireguard_plugin.reconfigure(updated_config)
        _replace_plugin_tasks(
            scheduler,
            (
                _build_wireguard_tasks(
                    wireguard_config=updated_config,
                    interval_seconds=configuration.interval_seconds,
                    start_at=resolved_clock.now(),
                )
                if configuration.enabled
                else []
            ),
            plugin_name="wireguard",
        )
        wireguard_plugin_config = configuration

    def apply_home_assistant_telemetry_configuration(
        configuration: HomeAssistantTelemetryPluginConfig,
    ) -> None:
        nonlocal home_assistant_telemetry_plugin_config

        updated_config = HomeAssistantTelemetryConfigurationBuilder().build(
            current_infrastructure,
            configuration,
        )
        home_assistant_telemetry_plugin.reconfigure(updated_config)
        _replace_plugin_tasks(
            scheduler,
            (
                _build_home_assistant_telemetry_tasks(
                    home_assistant_telemetry_config=updated_config,
                    interval_seconds=configuration.interval_seconds,
                    start_at=resolved_clock.now(),
                )
                if configuration.enabled
                else []
            ),
            plugin_name="home_assistant_telemetry",
        )
        home_assistant_telemetry_plugin_config = configuration

    def apply_teleinformation_configuration(
        configuration: TeleinformationPluginConfig,
    ) -> None:
        nonlocal teleinformation_plugin_config

        updated_config = TeleinformationConfigurationBuilder().build(
            current_infrastructure,
            configuration,
        )
        teleinformation_plugin.reconfigure(updated_config)
        agent.replace_teleinformation_ingestion_runtime(
            _build_teleinformation_ingestion_runtime(
                configuration=configuration,
                frame_store=teleinformation_frame_store,
            )
        )
        _replace_plugin_tasks(
            scheduler,
            (
                _build_teleinformation_tasks(
                    teleinformation_config=updated_config,
                    interval_seconds=configuration.interval_seconds,
                    start_at=resolved_clock.now(),
                )
                if configuration.enabled
                else []
            ),
            plugin_name="teleinformation",
        )
        teleinformation_plugin_config = configuration

    def apply_backup_configuration(configuration: BackupPluginConfig) -> None:
        nonlocal backup_plugin_config, backup_config

        updated_config = BackupConfigurationBuilder().build(configuration)
        backup_plugin.reconfigure(updated_config)
        _replace_plugin_tasks(
            scheduler,
            (
                _build_backup_tasks(backup_config=updated_config)
                if configuration.enabled
                else []
            ),
            plugin_name="backup",
        )
        backup_plugin_config = configuration
        backup_config = updated_config

    def test_dhcp_plugin() -> ObserverResult:
        servers = [server for server in dhcp_plugin.config.servers if server.enabled]

        if not servers:
            raise ValueError("The DHCP plugin has no enabled DHCP service.")

        return dhcp_plugin.execute(
            server=servers[0].address,
            port=servers[0].port,
            service_id=servers[0].name,
        )

    def test_backup_plugin() -> ObserverResult:
        return backup_plugin.test()

    def test_network_plugin() -> ObserverResult:
        devices = [device for device in network_plugin.config.devices if device.enabled]

        if not devices:
            raise ValueError("The network plugin has no addressable device.")

        device = devices[0]
        return network_plugin.test(
            address=device.address,
            device_id=device.name,
            label=device.label,
            node_id=device.node_id,
        )

    def test_dns_plugin() -> ObserverResult:
        servers = [server for server in dns_plugin.servers if server.enabled]

        if not dns_plugin.config.queries:
            raise ValueError("The DNS plugin has no configured query.")

        if not servers:
            raise ValueError("The DNS plugin has no enabled DNS service.")

        return dns_plugin.execute(
            hostname=dns_plugin.config.queries[0],
            server=servers[0].address,
        )

    def test_ntp_plugin() -> ObserverResult:
        servers = [server for server in ntp_plugin.config.servers if server.enabled]

        if not servers:
            raise ValueError("The NTP plugin has no enabled NTP service.")

        return ntp_plugin.execute(
            server=servers[0].address,
            port=servers[0].port,
        )

    def test_mqtt_plugin() -> ObserverResult:
        brokers = [broker for broker in mqtt_plugin.config.brokers if broker.enabled]

        if not brokers:
            raise ValueError("The MQTT plugin has no enabled MQTT service.")

        return mqtt_plugin.execute(
            broker=brokers[0].address,
            port=brokers[0].port,
            service_id=brokers[0].name,
        )

    def test_zwave_plugin() -> ObserverResult:
        services = [
            service for service in zwave_plugin.config.services if service.enabled
        ]

        if not services:
            raise ValueError("The Z-Wave plugin has no enabled Z-Wave service.")

        return zwave_plugin.execute(url=services[0].url)

    def test_wireguard_plugin() -> ObserverResult:
        services = [
            service for service in wireguard_plugin.config.services if service.enabled
        ]

        if not services:
            raise ValueError("The WireGuard plugin has no enabled WireGuard service.")

        service = services[0]
        return wireguard_plugin.execute(
            service_id=service.name,
            base_url=service.base_url,
            server_name=service.server_name,
        )

    def test_home_assistant_telemetry_plugin() -> ObserverResult:
        services = [
            service
            for service in home_assistant_telemetry_plugin.config.services
            if service.enabled
        ]

        if not services:
            raise ValueError(
                "The Home Assistant telemetry"
                "plugin has no enabled Home"
                "Assistant telemetry service."
            )

        service = services[0]
        return home_assistant_telemetry_plugin.execute(
            service_id=service.name,
            service_name=service.label,
            node_id=service.node_id,
            primary_entity_id=service.primary_entity_id,
            secondary_entity_id=service.secondary_entity_id,
            maximum_age_seconds=service.maximum_age_seconds,
        )

    def test_teleinformation_plugin() -> ObserverResult:
        services = [
            service
            for service in teleinformation_plugin.config.services
            if service.enabled
        ]

        if not services:
            raise ValueError(
                "The Téléinformation plugin has no enabled Téléinformation service."
            )

        service = services[0]
        return teleinformation_plugin.execute(
            service_id=service.name,
            service_name=service.label,
            node_id=service.node_id,
            source_id=service.source_id,
            meter_id=service.meter_id,
            apparent_power_entity_id=service.apparent_power_entity_id,
            tariff_entity_id=service.tariff_entity_id,
            blue_off_peak_entity_id=service.blue_off_peak_entity_id,
            blue_peak_entity_id=service.blue_peak_entity_id,
            white_off_peak_entity_id=service.white_off_peak_entity_id,
            white_peak_entity_id=service.white_peak_entity_id,
            red_off_peak_entity_id=service.red_off_peak_entity_id,
            red_peak_entity_id=service.red_peak_entity_id,
            maximum_age_seconds=service.maximum_age_seconds,
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
        administration_config = configuration.administration

        try:
            administration_token = administration_config.token_file.read_text(
                encoding="utf-8"
            ).strip()
        except OSError as error:
            raise ValueError(
                "Unable to read the Ohana administration token from "
                f"{administration_config.token_file}."
            ) from error

        dhcp_repository = None
        network_repository = None

        if administration_config.network.enabled:
            administration_network_config = administration_config.network
            network_repository = NetworkManagerRepository(
                helper_path=administration_network_config.helper_path,
                sudo_path=administration_network_config.sudo_path,
                rollback_seconds=administration_network_config.rollback_seconds,
            )

        if administration_config.dhcp.enabled:
            administration_dhcp_config = administration_config.dhcp
            dhcp_repository = DnsmasqDHCPRepository(
                main_config_path=administration_dhcp_config.main_config_path,
                reservation_paths={
                    "infrastructure": (
                        administration_dhcp_config.infrastructure_reservations_path
                    ),
                    "servers": administration_dhcp_config.server_reservations_path,
                    "network": administration_dhcp_config.network_reservations_path,
                    "home_automation": (
                        administration_dhcp_config.home_automation_reservations_path
                    ),
                    "critical": administration_dhcp_config.critical_reservations_path,
                },
                leases_path=administration_dhcp_config.leases_path,
                server_node_id=administration_dhcp_config.server_node_id,
                validation_command=administration_dhcp_config.validation_command,
                reload_request_path=administration_dhcp_config.reload_request_path,
            )

        plugin_repository = PluginAdministrationRepository(
            plugin_manager=plugin_manager,
            scheduler=scheduler,
            backup_runner=lambda arguments: dispatcher.execute(
                "backup.run",
                arguments,
            ),
            bindings=(
                PluginAdministrationBinding(
                    identifier="backup",
                    display_name="Sauvegardes HAOS",
                    capabilities=("backup.run",),
                    configuration_path=backup_config_path,
                    configuration_model=BackupPluginConfig,
                    apply_configuration=lambda config: agent.apply_plugin_configuration(
                        lambda: apply_backup_configuration(config)
                    ),
                    test_plugin=test_backup_plugin,
                ),
                PluginAdministrationBinding(
                    identifier="dhcp",
                    display_name="DHCP",
                    capabilities=("dhcp.status",),
                    configuration_path=dhcp_config_path,
                    configuration_model=DHCPPluginConfig,
                    apply_configuration=lambda config: agent.apply_plugin_configuration(
                        lambda: apply_dhcp_configuration(config)
                    ),
                    test_plugin=test_dhcp_plugin,
                ),
                PluginAdministrationBinding(
                    identifier="dns",
                    display_name="DNS",
                    capabilities=("dns.resolve",),
                    configuration_path=dns_config_path,
                    configuration_model=DNSPluginConfig,
                    apply_configuration=lambda config: agent.apply_plugin_configuration(
                        lambda: apply_dns_configuration(config)
                    ),
                    test_plugin=test_dns_plugin,
                ),
                PluginAdministrationBinding(
                    identifier="ntp",
                    display_name="NTP",
                    capabilities=("ntp.query",),
                    configuration_path=ntp_config_path,
                    configuration_model=NTPPluginConfig,
                    apply_configuration=lambda config: agent.apply_plugin_configuration(
                        lambda: apply_ntp_configuration(config)
                    ),
                    test_plugin=test_ntp_plugin,
                ),
                PluginAdministrationBinding(
                    identifier="mqtt",
                    display_name="MQTT",
                    capabilities=("mqtt.roundtrip",),
                    configuration_path=mqtt_config_path,
                    configuration_model=MQTTPluginConfig,
                    apply_configuration=lambda config: agent.apply_plugin_configuration(
                        lambda: apply_mqtt_configuration(config)
                    ),
                    test_plugin=test_mqtt_plugin,
                ),
                PluginAdministrationBinding(
                    identifier="zwave",
                    display_name="Z-Wave",
                    capabilities=("zwave.status",),
                    configuration_path=zwave_config_path,
                    configuration_model=ZWavePluginConfig,
                    apply_configuration=lambda config: agent.apply_plugin_configuration(
                        lambda: apply_zwave_configuration(config)
                    ),
                    test_plugin=test_zwave_plugin,
                ),
                PluginAdministrationBinding(
                    identifier="wireguard",
                    display_name="WireGuard",
                    capabilities=("wireguard.status",),
                    configuration_path=wireguard_config_path,
                    configuration_model=WireGuardPluginConfig,
                    apply_configuration=lambda config: agent.apply_plugin_configuration(
                        lambda: apply_wireguard_configuration(config)
                    ),
                    test_plugin=test_wireguard_plugin,
                ),
                PluginAdministrationBinding(
                    identifier="home_assistant_telemetry",
                    display_name="Télémétrie Home Assistant",
                    capabilities=("home_assistant.telemetry.freshness",),
                    configuration_path=home_assistant_telemetry_config_path,
                    configuration_model=HomeAssistantTelemetryPluginConfig,
                    apply_configuration=lambda config: agent.apply_plugin_configuration(
                        lambda: apply_home_assistant_telemetry_configuration(config)
                    ),
                    test_plugin=test_home_assistant_telemetry_plugin,
                ),
                PluginAdministrationBinding(
                    identifier="teleinformation",
                    display_name="Téléinformation",
                    capabilities=("teleinformation.freshness",),
                    configuration_path=teleinformation_config_path,
                    configuration_model=TeleinformationPluginConfig,
                    apply_configuration=lambda config: agent.apply_plugin_configuration(
                        lambda: apply_teleinformation_configuration(config)
                    ),
                    test_plugin=test_teleinformation_plugin,
                ),
                PluginAdministrationBinding(
                    identifier="network",
                    display_name="Présence réseau",
                    capabilities=("network.reachable",),
                    configuration_path=network_config_path,
                    configuration_model=NetworkPluginConfig,
                    apply_configuration=lambda config: agent.apply_plugin_configuration(
                        lambda: apply_network_configuration(config)
                    ),
                    test_plugin=test_network_plugin,
                ),
            ),
        )

        administration_service = AdministrationService(
            infrastructure_repository=(
                InfrastructureConfigurationRepository(
                    infrastructure_config_path,
                )
            ),
            dhcp_repository=dhcp_repository,
            plugin_repository=plugin_repository,
            network_repository=network_repository,
            on_infrastructure_changed=lambda changed_configuration: (
                agent.apply_infrastructure_configuration(
                    changed_configuration,
                    VisionInfrastructureMapper().to_payload(changed_configuration),
                )
            ),
        )
        agent.administration_runtime = AdministrationHTTPServer(
            service=administration_service,
            token=administration_token,
            host=str(administration_config.host),
            port=administration_config.port,
        )

    return agent
