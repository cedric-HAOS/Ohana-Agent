"""Production bootstrap for Ohana-Agent."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from administration import (
    AdministrationHTTPServer,
    AdministrationService,
    DnsmasqDHCPRepository,
    InfrastructureConfigurationRepository,
    PluginAdministrationBinding,
    PluginAdministrationRepository,
)
from builder import (
    DHCPConfigurationBuilder,
    DNSConfigurationBuilder,
    InfrastructureBuilder,
    MQTTConfigurationBuilder,
    NetworkConfigurationBuilder,
    NTPConfigurationBuilder,
    ShellyTelemetryConfigurationBuilder,
    WireGuardConfigurationBuilder,
    ZWaveConfigurationBuilder,
)
from configuration.dhcp import DHCPPluginConfig
from configuration.dns import DNSPluginConfig
from configuration.infrastructure import InfrastructureConfig
from configuration.infrastructure_validator import (
    InfrastructureValidator,
)
from configuration.loader import ConfigurationLoader
from configuration.mqtt_plugin import MQTTPluginConfig
from configuration.network import NetworkPluginConfig
from configuration.ntp import NTPPluginConfig
from configuration.shelly_telemetry import ShellyTelemetryPluginConfig
from configuration.wireguard import WireGuardPluginConfig
from configuration.zwave import ZWavePluginConfig
from core.events import EventBus
from infrastructure import InfrastructureRuntime
from infrastructure.infrastructure_health_manager import (
    InfrastructureHealthManager,
)
from loader import (
    DHCPConfigLoader,
    DNSConfigLoader,
    InfrastructureLoader,
    MQTTConfigLoader,
    NetworkConfigLoader,
    NTPConfigLoader,
    ShellyTelemetryConfigLoader,
    WireGuardConfigLoader,
    ZWaveConfigLoader,
)
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
    HttpVisionClient,
    VisionClient,
    VisionInfrastructureMapper,
    VisionObservationExporter,
    VisionObservationMapper,
)
from plugin.plugin_context import PluginContext
from plugin.plugin_manager import PluginManager
from plugins.dhcp.dhcp_check import DHCPCheck
from plugins.dhcp.dhcp_config import DHCPConfig
from plugins.dhcp.dhcp_plugin import DHCPPlugin
from plugins.dns.dns_check import DNSCheck
from plugins.dns.dns_config import DNSConfig
from plugins.dns.dns_plugin import DNSPlugin
from plugins.mqtt.home_assistant_publisher import MQTTHomeAssistantPublisher
from plugins.mqtt.mqtt_check import MQTTCheck
from plugins.mqtt.mqtt_config import MQTTConfig
from plugins.mqtt.mqtt_plugin import MQTTPlugin
from plugins.network.network_check import NetworkCheck
from plugins.network.network_config import NetworkConfig
from plugins.network.network_plugin import NetworkPlugin
from plugins.ntp.ntp_check import NTPCheck
from plugins.ntp.ntp_config import NTPConfig
from plugins.ntp.ntp_plugin import NTPPlugin
from plugins.shelly_telemetry.shelly_telemetry_check import ShellyTelemetryCheck
from plugins.shelly_telemetry.shelly_telemetry_config import ShellyTelemetryConfig
from plugins.shelly_telemetry.shelly_telemetry_plugin import ShellyTelemetryPlugin
from plugins.wireguard.wireguard_check import WireGuardCheck
from plugins.wireguard.wireguard_config import WireGuardConfig
from plugins.wireguard.wireguard_plugin import WireGuardPlugin
from plugins.zwave.zwave_check import ZWaveCheck
from plugins.zwave.zwave_config import ZWaveConfig
from plugins.zwave.zwave_plugin import ZWavePlugin
from production_agent import ProductionAgent
from scheduler import (
    DispatcherTaskExecutor,
    IntervalTrigger,
    Scheduler,
    Task,
)
from scheduler.clock import Clock, SystemClock


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
                "service_id": service.name,
                "base_url": service.base_url,
                "server_name": service.server_name,
            },
        )
        for service in wireguard_config.services
        if service.enabled
    ]


def _build_shelly_telemetry_tasks(
    *,
    shelly_telemetry_config: ShellyTelemetryConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one telemetry freshness observation per declared service."""
    return [
        Task(
            id=f"shelly.telemetry.freshness:{service.name}",
            name=f"Check Shelly telemetry service {service.name}",
            command="shelly.telemetry.freshness",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "service_id": service.name,
                "service_name": service.label,
                "node_id": service.node_id,
                "power_entity_id": service.power_entity_id,
                "energy_entity_id": service.energy_entity_id,
                "maximum_age_seconds": service.maximum_age_seconds,
            },
            metadata={
                "managed_by": "shelly_telemetry",
                "service_id": service.name,
                "service_name": service.label,
                "node_id": service.node_id,
                "power_entity_id": service.power_entity_id,
                "energy_entity_id": service.energy_entity_id,
                "maximum_age_seconds": service.maximum_age_seconds,
            },
        )
        for service in shelly_telemetry_config.services
        if service.enabled
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
    shelly_telemetry_config_path: Path = Path("config/plugins/shelly-telemetry.yaml"),
    vision_client: VisionClient | None = None,
    clock: Clock | None = None,
    network_check: NetworkCheck | None = None,
    dhcp_check: DHCPCheck | None = None,
    zwave_check: ZWaveCheck | None = None,
    wireguard_check: WireGuardCheck | None = None,
    shelly_telemetry_check: ShellyTelemetryCheck | None = None,
) -> ProductionAgent:
    """Build the complete production Ohana-Agent runtime."""
    configuration = ConfigurationLoader.load(application_config_path)
    dhcp_service_config = configuration.administration.dhcp

    infrastructure_config = InfrastructureLoader().load(infrastructure_config_path)
    InfrastructureValidator().validate(infrastructure_config)
    infrastructure = InfrastructureBuilder().build(infrastructure_config)
    current_infrastructure = infrastructure
    current_infrastructure_config = infrastructure_config
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

    shelly_telemetry_plugin_config = ShellyTelemetryConfigLoader().load(
        shelly_telemetry_config_path
    )
    shelly_telemetry_config = ShellyTelemetryConfigurationBuilder().build(
        infrastructure,
        shelly_telemetry_plugin_config,
    )

    event_bus = EventBus()

    resolved_vision_client = vision_client

    if resolved_vision_client is None:
        if not configuration.vision.enabled:
            raise ValueError(
                "Ohana-Vision export must be enabled for the production bootstrap."
            )

        resolved_vision_client = HttpVisionClient(
            observation_url=str(configuration.vision.observation_url),
            infrastructure_url=str(configuration.vision.infrastructure_url),
            timeout_seconds=(configuration.vision.timeout_seconds),
        )

    mqtt_home_assistant_publisher = MQTTHomeAssistantPublisher(
        config=mqtt_config,
        infrastructure=infrastructure_config,
    )

    export_handler = ObservationExportHandler(
        pipeline=ObservationExportPipeline(
            exporters=[
                VisionObservationExporter(
                    client=resolved_vision_client,
                    mapper=VisionObservationMapper(),
                ),
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

    shelly_telemetry_plugin = ShellyTelemetryPlugin(
        check=shelly_telemetry_check or ShellyTelemetryCheck(),
        config=shelly_telemetry_config,
    )
    plugin_manager.register(shelly_telemetry_plugin)

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
            _build_shelly_telemetry_tasks(
                shelly_telemetry_config=shelly_telemetry_config,
                interval_seconds=(shelly_telemetry_plugin_config.interval_seconds),
                start_at=resolved_clock.now(),
            )
            if shelly_telemetry_plugin_config.enabled
            else []
        ),
        plugin_name="shelly_telemetry",
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
        updated_shelly_telemetry_config = ShellyTelemetryConfigurationBuilder().build(
            updated_infrastructure,
            shelly_telemetry_plugin_config,
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
        updated_shelly_telemetry_tasks = (
            _build_shelly_telemetry_tasks(
                shelly_telemetry_config=updated_shelly_telemetry_config,
                interval_seconds=shelly_telemetry_plugin_config.interval_seconds,
                start_at=resolved_clock.now(),
            )
            if shelly_telemetry_plugin_config.enabled
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
        shelly_telemetry_plugin.reconfigure(updated_shelly_telemetry_config)
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
            updated_shelly_telemetry_tasks,
            plugin_name="shelly_telemetry",
        )
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

    def apply_shelly_telemetry_configuration(
        configuration: ShellyTelemetryPluginConfig,
    ) -> None:
        nonlocal shelly_telemetry_plugin_config

        updated_config = ShellyTelemetryConfigurationBuilder().build(
            current_infrastructure_config,
            configuration,
        )
        shelly_telemetry_plugin.reconfigure(updated_config)
        _replace_plugin_tasks(
            scheduler,
            (
                _build_shelly_telemetry_tasks(
                    shelly_telemetry_config=updated_config,
                    interval_seconds=configuration.interval_seconds,
                    start_at=resolved_clock.now(),
                )
                if configuration.enabled
                else []
            ),
            plugin_name="shelly_telemetry",
        )
        shelly_telemetry_plugin_config = configuration

    def test_dhcp_plugin() -> ObserverResult:
        servers = [server for server in dhcp_plugin.config.servers if server.enabled]

        if not servers:
            raise ValueError("The DHCP plugin has no enabled DHCP service.")

        return dhcp_plugin.execute(
            server=servers[0].address,
            port=servers[0].port,
            service_id=servers[0].name,
        )

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

    def test_shelly_telemetry_plugin() -> ObserverResult:
        services = [
            service
            for service in shelly_telemetry_plugin.config.services
            if service.enabled
        ]

        if not services:
            raise ValueError(
                "The Shelly telemetry plugin has no enabled Shelly telemetry service."
            )

        service = services[0]
        return shelly_telemetry_plugin.execute(
            service_id=service.name,
            service_name=service.label,
            node_id=service.node_id,
            power_entity_id=service.power_entity_id,
            energy_entity_id=service.energy_entity_id,
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
        home_assistant_publisher=mqtt_home_assistant_publisher,
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
            bindings=(
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
                    identifier="shelly_telemetry",
                    display_name="Shelly Telemetry",
                    capabilities=("shelly.telemetry.freshness",),
                    configuration_path=shelly_telemetry_config_path,
                    configuration_model=ShellyTelemetryPluginConfig,
                    apply_configuration=lambda config: agent.apply_plugin_configuration(
                        lambda: apply_shelly_telemetry_configuration(config)
                    ),
                    test_plugin=test_shelly_telemetry_plugin,
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
