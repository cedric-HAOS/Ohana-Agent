"""Display a visual infrastructure status demo."""

from ohana_agent.infrastructure import (
    HealthStatus,
    Infrastructure,
    InfrastructureCapabilityCalculator,
    InfrastructureRuntime,
    Node,
    Observation,
    ObservationManager,
    SchedulerObservationHandler,
    Service,
    ServiceType,
)


def build_demo_infrastructure() -> Infrastructure:
    """Build a demo infrastructure."""
    return Infrastructure(
        name="Ohana",
        nodes=[
            Node(
                name="INFRA-01",
                description="Infrastructure server",
                services=[
                    Service(name="DNS", type=ServiceType.DNS),
                    Service(name="MQTT", type=ServiceType.MQTT),
                ],
            ),
            Node(
                name="HA-01",
                description="Home Assistant Green",
                services=[
                    Service(name="Home Assistant", type=ServiceType.HOME_ASSISTANT),
                ],
            ),
        ],
    )


def status_icon(health: HealthStatus) -> str:
    """Return a visual icon for a health status."""
    match health:
        case HealthStatus.HEALTHY:
            return "✅"
        case HealthStatus.DEGRADED:
            return "⚠️"
        case HealthStatus.UNHEALTHY:
            return "❌"
        case HealthStatus.UNKNOWN:
            return "❔"


def print_runtime(runtime: InfrastructureRuntime) -> None:
    """Print infrastructure runtime status."""
    print()
    print("OHANA INFRASTRUCTURE STATUS")
    print("=" * 80)

    for node_runtime in runtime.node_runtimes:
        node = node_runtime.node
        print()
        print(
            f"{status_icon(node_runtime.health)} "
            f"{node.name:<12} "
            f"{node_runtime.health.value:<10} "
            f"{node.description}"
        )

        for service_runtime in node_runtime.service_runtimes:
            service = service_runtime.service
            print(
                f"   └─ {status_icon(service_runtime.health)} "
                f"{service.name:<18} "
                f"{service.type.value:<16} "
                f"{service_runtime.health.value}"
            )


def print_capabilities(calculator: InfrastructureCapabilityCalculator) -> None:
    """Print calculated infrastructure capabilities."""
    capabilities = [
        calculator.calculate_dns_available(),
        calculator.calculate_mqtt_available(),
    ]

    print()
    print("CALCULATED CAPABILITIES")
    print("=" * 80)

    for capability in capabilities:
        icon = "✅" if capability.available else "❌"
        print(
            f"{icon} {capability.name:<20} "
            f"available={str(capability.available):<5} "
            f"health={capability.health.value:<10} "
            f"reason={capability.reason}"
        )


def main() -> None:
    """Run the infrastructure status demo."""
    infrastructure = build_demo_infrastructure()
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    manager = ObservationManager(runtime=runtime)
    handler = SchedulerObservationHandler(observation_manager=manager)

    handler.handle_success(
        target_name="dns",
        source="demo-scheduler",
        message="DNS resolution succeeded",
    )

    handler.handle_failure(
        target_name="mqtt",
        source="demo-scheduler",
        message="MQTT broker unreachable",
    )

    manager.record(
        Observation(
            target_name="HA-01",
            health=HealthStatus.DEGRADED,
            source="demo-observer",
            message="Home Assistant responds slowly",
        )
    )

    calculator = InfrastructureCapabilityCalculator(runtime=runtime)

    print_runtime(runtime)
    print_capabilities(calculator)

    print()
    print("OBSERVATIONS")
    print("=" * 80)

    for observation in manager.observations:
        print(
            f"- {observation.source:<15} "
            f"target={observation.target_name:<8} "
            f"health={observation.health.value:<10} "
            f"message={observation.message}"
        )


if __name__ == "__main__":
    main()
