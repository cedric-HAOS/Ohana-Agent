from ohana_agent.observation import ObservationFactory, ObservationStatus


def test_factory_creates_observation() -> None:
    factory = ObservationFactory()

    observation = factory.create(
        node="infra-01",
        service="dns-primary",
        capability="dns",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="Everything is OK.",
        source="dns-plugin",
        latency_ms=10.5,
        metadata={
            "hostname": "example.com",
        },
    )

    assert observation.node == "infra-01"
    assert observation.service == "dns-primary"
    assert observation.capability == "dns"

    assert observation.status == ObservationStatus.HEALTHY
    assert observation.success is True

    assert observation.latency_ms == 10.5

    assert observation.metadata["hostname"] == "example.com"


def test_factory_creates_empty_metadata() -> None:
    factory = ObservationFactory()

    observation = factory.create(
        node="infra-01",
        service="dns-primary",
        capability="dns",
        status=ObservationStatus.UNKNOWN,
        success=False,
        message="Unknown",
        source="test",
    )

    assert observation.metadata == {}
