from ohana_agent.infrastructure import HealthStatus
from ohana_agent.infrastructure.infrastructure_health_update import (
    InfrastructureHealthUpdate,
)


def test_infrastructure_health_update_contains_target_health_and_source() -> None:
    update = InfrastructureHealthUpdate(
        target_name="dns",
        health=HealthStatus.HEALTHY,
        source="dns.resolve",
    )

    assert update.target_name == "dns"
    assert update.health is HealthStatus.HEALTHY
    assert update.source == "dns.resolve"


def test_infrastructure_health_update_has_default_values() -> None:
    update = InfrastructureHealthUpdate(
        target_name="INFRA-01",
        health=HealthStatus.UNKNOWN,
        source="node.ping",
    )

    assert update.message == ""
    assert update.metadata == {}
    assert update.timestamp is not None
