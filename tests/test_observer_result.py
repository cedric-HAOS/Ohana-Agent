from datetime import UTC, datetime

from ohana_agent.observation import ObserverResult


def test_observer_result_stores_success() -> None:
    result = ObserverResult(success=True, latency=12.5)

    assert result.success is True


def test_observer_result_stores_failure() -> None:
    result = ObserverResult(success=False, latency=12.5)

    assert result.success is False


def test_observer_result_stores_latency() -> None:
    result = ObserverResult(success=True, latency=42.7)

    assert result.latency == 42.7


def test_observer_result_has_default_timestamp() -> None:
    result = ObserverResult(success=True, latency=1.0)

    assert isinstance(result.timestamp, datetime)
    assert result.timestamp.tzinfo is not None


def test_observer_result_accepts_custom_timestamp() -> None:
    timestamp = datetime(2026, 7, 8, 20, 0, tzinfo=UTC)

    result = ObserverResult(
        success=True,
        latency=1.0,
        timestamp=timestamp,
    )

    assert result.timestamp == timestamp


def test_observer_result_message_defaults_to_none() -> None:
    result = ObserverResult(success=True, latency=1.0)

    assert result.message is None


def test_observer_result_stores_message() -> None:
    result = ObserverResult(
        success=False,
        latency=1.0,
        message="DNS resolution failed",
    )

    assert result.message == "DNS resolution failed"


def test_observer_result_metadata_defaults_to_empty_dict() -> None:
    result = ObserverResult(success=True, latency=1.0)

    assert result.metadata == {}


def test_observer_result_metadata_is_not_shared() -> None:
    first = ObserverResult(success=True, latency=1.0)
    second = ObserverResult(success=True, latency=1.0)

    first.metadata["hostname"] = "example.com"

    assert second.metadata == {}


def test_observer_result_stores_metadata() -> None:
    result = ObserverResult(
        success=True,
        latency=24.0,
        metadata={
            "hostname": "example.com",
            "address": "93.184.216.34",
        },
    )

    assert result.metadata["hostname"] == "example.com"
    assert result.metadata["address"] == "93.184.216.34"


def test_observer_result_check_defaults_to_none() -> None:
    result = ObserverResult(success=True, latency=1.0)

    assert result.check is None


def test_observer_result_stores_check() -> None:
    result = ObserverResult(
        success=True,
        latency=1.0,
        check="dns.resolve",
    )

    assert result.check == "dns.resolve"


def test_observer_result_description_defaults_to_none() -> None:
    result = ObserverResult(success=True, latency=1.0)

    assert result.description is None


def test_observer_result_stores_description() -> None:
    result = ObserverResult(
        success=True,
        latency=1.0,
        description="Resolve example.com",
    )

    assert result.description == "Resolve example.com"
