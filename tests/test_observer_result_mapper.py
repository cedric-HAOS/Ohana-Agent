from datetime import UTC, datetime

import pytest

from ohana_agent.infrastructure import HealthStatus
from ohana_agent.observation import ObserverResult
from ohana_agent.observation.observer_result_mapper import ObserverResultMapper


def test_mapper_converts_successful_observer_result() -> None:
    timestamp = datetime.now(UTC)
    result = ObserverResult(
        success=True,
        latency=12.5,
        timestamp=timestamp,
        message="DNS resolution succeeded.",
        check="dns.resolve",
        metadata={
            "hostname": "example.com",
            "address": "93.184.216.34",
        },
    )

    mapper = ObserverResultMapper()

    update = mapper.map(
        result,
        target_name="dns",
    )

    assert update.target_name == "dns"
    assert update.health is HealthStatus.HEALTHY
    assert update.source == "dns.resolve"
    assert update.message == "DNS resolution succeeded."
    assert update.timestamp is timestamp
    assert update.metadata == {
        "hostname": "example.com",
        "address": "93.184.216.34",
    }


def test_mapper_converts_failed_observer_result() -> None:
    result = ObserverResult(
        success=False,
        latency=0.0,
        message="DNS resolution failed.",
        check="dns.resolve",
    )

    mapper = ObserverResultMapper()

    update = mapper.map(
        result,
        target_name="dns",
    )

    assert update.health is HealthStatus.UNHEALTHY
    assert update.message == "DNS resolution failed."


def test_mapper_uses_explicit_source() -> None:
    result = ObserverResult(
        success=True,
        latency=1.0,
        check=None,
    )

    mapper = ObserverResultMapper()

    update = mapper.map(
        result,
        target_name="dns",
        source="dns.custom",
    )

    assert update.source == "dns.custom"


def test_mapper_converts_none_message_to_empty_string() -> None:
    result = ObserverResult(
        success=True,
        latency=1.0,
        check="dns.resolve",
        message=None,
    )

    mapper = ObserverResultMapper()

    update = mapper.map(
        result,
        target_name="dns",
    )

    assert update.message == ""


def test_mapper_copies_metadata() -> None:
    result = ObserverResult(
        success=True,
        latency=1.0,
        check="dns.resolve",
        metadata={"server": "192.168.1.54"},
    )

    mapper = ObserverResultMapper()

    update = mapper.map(
        result,
        target_name="dns",
    )

    result.metadata["server"] = "8.8.8.8"

    assert update.metadata == {"server": "192.168.1.54"}


def test_mapper_rejects_empty_target_name() -> None:
    result = ObserverResult(
        success=True,
        latency=1.0,
        check="dns.resolve",
    )

    mapper = ObserverResultMapper()

    with pytest.raises(
        ValueError,
        match="target_name must not be empty",
    ):
        mapper.map(
            result,
            target_name="",
        )


def test_mapper_requires_source_or_check() -> None:
    result = ObserverResult(
        success=True,
        latency=1.0,
    )

    mapper = ObserverResultMapper()

    with pytest.raises(
        ValueError,
        match="must define a check or an explicit source",
    ):
        mapper.map(
            result,
            target_name="dns",
        )
