"""Run a real DNS check from declarative Ohana-Agent configuration."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ohana_agent.configuration.builders import (
    DNSConfigurationBuilder,
    InfrastructureBuilder,
)
from ohana_agent.configuration.loaders import DNSConfigLoader, InfrastructureLoader
from ohana_agent.core.events import EventBus
from ohana_agent.infrastructure import InfrastructureRuntime, ServiceType
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
    ObservationSerializer,
    ObserverResultMapper,
    PluginObservationDispatcher,
    PluginObservationExecutor,
)
from ohana_agent.observation.exporters.vision_observation_exporter import (
    VisionObservationExporter,
)
from ohana_agent.plugins.dns.check import DNSCheck
from ohana_agent.plugins.dns.check_result import DNSCheckResult
from ohana_agent.plugins.dns.plugin import DNSPlugin
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_manager import PluginManager
from ohana_agent.scheduler.clock import FakeClock
from ohana_agent.scheduler.dispatcher_task_executor import DispatcherTaskExecutor
from ohana_agent.scheduler.oneshot_trigger import OneShotTrigger
from ohana_agent.scheduler.scheduler import Scheduler
from ohana_agent.scheduler.task import Task


class ConfiguredDNSCheck:
    """Execute real DNS queries through one configured DNS server."""

    def __init__(
        self,
        server: str,
        check: DNSCheck | None = None,
    ) -> None:
        self.server = server
        self._check = check or DNSCheck()

    def check(self, hostname: str) -> DNSCheckResult:
        """Resolve a hostname through the configured DNS server."""
        return self._check.check(
            hostname=hostname,
            server=self.server,
        )


class DemoVisionClient:
    """Store observations sent to the simulated Ohana-Vision client."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def send_observation(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Store a serialized observation payload."""
        self.payloads.append(payload)


def parse_arguments() -> argparse.Namespace:
    """Parse demonstration command-line arguments."""
    parser = argparse.ArgumentParser(
        description=("Execute a real DNS query using Ohana-Agent YAML configuration.")
    )

    parser.add_argument(
        "--infrastructure",
        type=Path,
        default=Path("config/infrastructure.yaml"),
        help=("Infrastructure YAML file. Default: config/infrastructure.yaml"),
    )
    parser.add_argument(
        "--dns-config",
        type=Path,
        default=Path("config/plugins/dns.yaml"),
        help=("DNS plugin YAML file. Default: config/plugins/dns.yaml"),
    )
    parser.add_argument(
        "--hostname",
        help=("Hostname to resolve. Defaults to the first query declared in dns.yaml."),
    )

    return parser.parse_args()


def build_plugin_context(
    event_bus: EventBus,
    runtime: InfrastructureRuntime,
) -> PluginContext:
    """Build the context provided to registered plugins."""
    return PluginContext(
        event_bus=event_bus,
        scheduler=object(),
        dispatcher=object(),
        memory=object(),
        capability_manager=object(),
        configuration=object(),
        runtime=runtime,
    )


def print_section(title: str) -> None:
    """Print a demonstration section."""
    print()
    print(title)
    print("-" * len(title))


def main() -> int:
    """Execute the complete real DNS observation pipeline."""
    arguments = parse_arguments()

    print("=" * 72)
    print("OHANA-AGENT — DECLARATIVE REAL DNS DEMONSTRATION")
    print("=" * 72)

    # Load the infrastructure source of truth.
    infrastructure_config = InfrastructureLoader().load(arguments.infrastructure)
    infrastructure = InfrastructureBuilder().build(infrastructure_config)
    infrastructure_runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    # Load the DNS plugin policy and resolve its infrastructure services.
    dns_plugin_config = DNSConfigLoader().load(arguments.dns_config)
    dns_config = DNSConfigurationBuilder().build(
        infrastructure,
        dns_plugin_config,
    )

    enabled_servers = [server for server in dns_config.servers if server.enabled]

    if not enabled_servers:
        print("ERROR: no enabled DNS server was resolved from configuration.")
        return 2

    if not dns_config.queries and not arguments.hostname:
        print("ERROR: dns.yaml does not declare any query.")
        return 2

    server = enabled_servers[0]
    hostname = arguments.hostname or dns_config.queries[0]

    print_section("Loaded configuration")
    print(f"Infrastructure file : {arguments.infrastructure}")
    print(f"DNS config file     : {arguments.dns_config}")
    print(f"Service ID          : {server.name}")
    print(f"Resolved DNS server : {server.address}")
    print(f"Hostname            : {hostname}")
    print("Mode                : real network query")

    event_bus = EventBus()
    vision_client = DemoVisionClient()

    export_handler = ObservationExportHandler(
        pipeline=ObservationExportPipeline(
            exporters=[
                VisionObservationExporter(
                    client=vision_client,
                    serializer=ObservationSerializer(),
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

    plugin_manager = PluginManager(
        context=build_plugin_context(
            event_bus,
            infrastructure_runtime,
        )
    )

    dns_plugin = DNSPlugin(
        check=ConfiguredDNSCheck(server.address),
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
    task_executor = DispatcherTaskExecutor(
        dispatcher=dispatcher,
    )

    now = datetime.now(UTC)

    scheduler = Scheduler(
        clock=FakeClock(current_time=now),
        executor=task_executor,
        event_bus=event_bus,
    )

    task = Task(
        name=f"Resolve {hostname} through {server.name}",
        command="dns.resolve",
        trigger=OneShotTrigger(run_at=now),
        arguments={
            "hostname": hostname,
        },
        metadata={
            "dns_service": server.name,
            "dns_server": server.address,
        },
    )

    scheduler.add_task(task)
    scheduler.start()

    execution_results = scheduler.tick()

    scheduler.stop()

    if not execution_results:
        print("ERROR: the scheduled DNS task was not executed.")
        return 2

    execution = execution_results[0]

    print_section("Scheduler execution")
    print(f"Task success : {execution.success}")
    print(f"Task ID      : {execution.task_id}")

    if execution.error:
        print(f"Pipeline error : {execution.error}")
        return 2

    if not vision_client.payloads:
        print("ERROR: no observation reached the Vision client.")
        return 2

    payload = vision_client.payloads[-1]

    print_section("Real DNS result")
    print(f"Service ID : {server.name}")
    print(f"DNS server : {server.address}")
    print(f"Hostname   : {payload['metadata']['hostname']}")
    print(f"Address    : {payload['metadata']['address']}")
    print(f"Latency    : {payload['latency_ms']:.2f} ms")
    print(f"Status     : {payload['status']}")
    print(f"Success    : {payload['success']}")

    if payload["metadata"]["error"]:
        print(f"Error      : {payload['metadata']['error']}")

    service_runtime = infrastructure_runtime.get_service_runtime_by_type(
        ServiceType.DNS
    )

    if service_runtime is None:
        print("ERROR: DNS service runtime was not found.")
        return 2

    print_section("Infrastructure runtime")
    print(f"Node    : {infrastructure.nodes[0].name}")
    print(f"Service : {service_runtime.service.name}")
    print(f"Health  : {service_runtime.health.value}")
    print(f"Updated : {service_runtime.last_update}")

    print_section("Payload exported to fake VisionClient")
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )

    print()
    print("=" * 72)

    if payload["success"]:
        print("REAL DNS DEMONSTRATION COMPLETED SUCCESSFULLY")
        print("=" * 72)
        return 0

    print("REAL DNS DEMONSTRATION COMPLETED WITH AN UNHEALTHY RESULT")
    print("=" * 72)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
