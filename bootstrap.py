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
    DNSConfigurationBuilder,
    InfrastructureBuilder,
    MQTTConfigurationBuilder,
    NTPConfigurationBuilder,
)
from configuration.dns import DNSPluginConfig
from configuration.infrastructure import InfrastructureConfig
from configuration.infrastructure_validator import (
    InfrastructureValidator,
)
from configuration.loader import ConfigurationLoader
from configuration.mqtt_plugin import MQTTPluginConfig
from configuration.ntp import NTPPluginConfig
from core.events import EventBus
from infrastructure import InfrastructureRuntime
from infrastructure.infrastructure_health_manager import (
    InfrastructureHealthManager,
)
from loader import (
    DNSConfigLoader,
    InfrastructureLoader,
    MQTTConfigLoader,
    NTPConfigLoader,
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
from plugins.dns.dns_check import DNSCheck
from plugins.dns.dns_config import DNSConfig
from plugins.dns.dns_plugin import DNSPlugin
from plugins.mqtt.mqtt_check import MQTTCheck
from plugins.mqtt.mqtt_config import MQTTConfig
from plugins.mqtt.mqtt_plugin import MQTTPlugin
from plugins.ntp.ntp_check import NTPCheck
from plugins.ntp.ntp_config import NTPConfig
from plugins.ntp.ntp_plugin import NTPPlugin
from production_agent import ProductionAgent
from scheduler import (
    DispatcherTaskExecutor,
    IntervalTrigger,
    Scheduler,
    Task,
)
from scheduler.clock import Clock, SystemClock


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
    dns_config_path: Path = Path("config/plugins/dns.yaml"),
    ntp_config_path: Path = Path("config/plugins/ntp.yaml"),
    mqtt_config_path: Path = Path("config/plugins/mqtt.yaml"),
    vision_client: VisionClient | None = None,
    clock: Clock | None = None,
) -> ProductionAgent:
    """Build the complete production Ohana-Agent runtime."""
    configuration = ConfigurationLoader.load(application_config_path)

    infrastructure_config = InfrastructureLoader().load(infrastructure_config_path)
    InfrastructureValidator().validate(infrastructure_config)
    infrastructure = InfrastructureBuilder().build(infrastructure_config)
    current_infrastructure = infrastructure
    infrastructure_runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

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

    export_handler = ObservationExportHandler(
        pipeline=ObservationExportPipeline(
            exporters=[
                VisionObservationExporter(
                    client=resolved_vision_client,
                    mapper=VisionObservationMapper(),
                )
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
    )
    plugin_manager.register(mqtt_plugin)

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

    def reconfigure_infrastructure(
        changed_configuration: InfrastructureConfig,
    ) -> None:
        nonlocal current_infrastructure

        updated_infrastructure = InfrastructureBuilder().build(changed_configuration)
        updated_runtime = InfrastructureRuntime.from_infrastructure(
            updated_infrastructure
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

        observation_engine.health_manager.runtime = updated_runtime
        dns_plugin.reconfigure(updated_dns_config)
        ntp_plugin.reconfigure(updated_ntp_config)
        mqtt_plugin.reconfigure(updated_mqtt_config)
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
        current_infrastructure = updated_infrastructure

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
            dhcp_config = administration_config.dhcp
            dhcp_repository = DnsmasqDHCPRepository(
                main_config_path=dhcp_config.main_config_path,
                reservation_paths={
                    "infrastructure": (dhcp_config.infrastructure_reservations_path),
                    "servers": dhcp_config.server_reservations_path,
                    "network": dhcp_config.network_reservations_path,
                    "home_automation": (dhcp_config.home_automation_reservations_path),
                    "critical": dhcp_config.critical_reservations_path,
                },
                leases_path=dhcp_config.leases_path,
                server_node_id=dhcp_config.server_node_id,
                validation_command=(dhcp_config.validation_command),
                reload_request_path=(dhcp_config.reload_request_path),
            )

        plugin_repository = PluginAdministrationRepository(
            plugin_manager=plugin_manager,
            scheduler=scheduler,
            bindings=(
                PluginAdministrationBinding(
                    identifier="dns",
                    display_name="DNS",
                    capabilities=("dns.resolve",),
                    configuration_path=dns_config_path,
                    configuration_model=DNSPluginConfig,
                    apply_configuration=lambda config: (
                        agent.apply_plugin_configuration(
                            lambda: apply_dns_configuration(config)
                        )
                    ),
                    test_plugin=test_dns_plugin,
                ),
                PluginAdministrationBinding(
                    identifier="ntp",
                    display_name="NTP",
                    capabilities=("ntp.query",),
                    configuration_path=ntp_config_path,
                    configuration_model=NTPPluginConfig,
                    apply_configuration=lambda config: (
                        agent.apply_plugin_configuration(
                            lambda: apply_ntp_configuration(config)
                        )
                    ),
                    test_plugin=test_ntp_plugin,
                ),
                PluginAdministrationBinding(
                    identifier="mqtt",
                    display_name="MQTT",
                    capabilities=("mqtt.roundtrip",),
                    configuration_path=mqtt_config_path,
                    configuration_model=MQTTPluginConfig,
                    apply_configuration=lambda config: (
                        agent.apply_plugin_configuration(
                            lambda: apply_mqtt_configuration(config)
                        )
                    ),
                    test_plugin=test_mqtt_plugin,
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
