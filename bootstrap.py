"""Production bootstrap for Ohana-Agent."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from administration import (
    AdministrationHTTPServer,
    AdministrationService,
    DnsmasqDHCPRepository,
    InfrastructureConfigurationRepository,
)
from builder import (
    DNSConfigurationBuilder,
    InfrastructureBuilder,
)
from configuration.infrastructure import InfrastructureConfig
from configuration.infrastructure_validator import (
    InfrastructureValidator,
)
from configuration.loader import ConfigurationLoader
from core.events import EventBus
from infrastructure import InfrastructureRuntime
from infrastructure.infrastructure_health_manager import (
    InfrastructureHealthManager,
)
from loader import DNSConfigLoader, InfrastructureLoader
from observer import (
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


def _replace_dns_tasks(
    scheduler: Scheduler,
    tasks: list[Task],
) -> None:
    """Atomically replace the scheduler tasks managed by the DNS plugin."""
    for task in scheduler.list_tasks():
        if task.command == "dns.resolve" or task.metadata.get("managed_by") == "dns":
            scheduler.remove_task(task.id)

    for task in tasks:
        scheduler.add_task(task)


def build_production_agent(
    *,
    application_config_path: Path = Path("config/shikamaru.yaml"),
    infrastructure_config_path: Path = Path("config/infrastructure.yaml"),
    dns_config_path: Path = Path("config/plugins/dns.yaml"),
    vision_client: VisionClient | None = None,
    clock: Clock | None = None,
) -> ProductionAgent:
    """Build the complete production Ohana-Agent runtime."""
    configuration = ConfigurationLoader.load(application_config_path)

    infrastructure_config = InfrastructureLoader().load(infrastructure_config_path)
    InfrastructureValidator().validate(infrastructure_config)
    infrastructure = InfrastructureBuilder().build(infrastructure_config)
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

    _replace_dns_tasks(
        scheduler,
        _build_dns_tasks(
            dns_config=dns_config,
            interval_seconds=dns_plugin_config.interval_seconds,
            start_at=resolved_clock.now(),
        ),
    )

    def reconfigure_infrastructure(
        changed_configuration: InfrastructureConfig,
    ) -> None:
        updated_infrastructure = InfrastructureBuilder().build(changed_configuration)
        updated_runtime = InfrastructureRuntime.from_infrastructure(
            updated_infrastructure
        )
        updated_dns_config = DNSConfigurationBuilder().build(
            updated_infrastructure,
            dns_plugin_config,
        )
        updated_tasks = _build_dns_tasks(
            dns_config=updated_dns_config,
            interval_seconds=dns_plugin_config.interval_seconds,
            start_at=resolved_clock.now(),
        )

        observation_engine.health_manager.runtime = updated_runtime
        dns_plugin.reconfigure(updated_dns_config)
        _replace_dns_tasks(scheduler, updated_tasks)

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

        administration_service = AdministrationService(
            infrastructure_repository=(
                InfrastructureConfigurationRepository(
                    infrastructure_config_path,
                )
            ),
            dhcp_repository=dhcp_repository,
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
