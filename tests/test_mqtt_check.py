"""Tests for MQTT retry behavior."""

import pytest

from plugins.mqtt.mqtt_check import MQTTCheck
from plugins.mqtt.mqtt_result import MQTTResult


class FakeMQTTClient:
    def __init__(self, results: list[MQTTResult]) -> None:
        self.results = results
        self.calls = 0

    def roundtrip(self, broker: str, **kwargs: object) -> MQTTResult:
        del broker, kwargs
        result = self.results[self.calls]
        self.calls += 1
        return result


def test_mqtt_check_retries_until_success() -> None:
    client = FakeMQTTClient(
        [
            MQTTResult(
                broker="192.168.1.247",
                port=1883,
                success=False,
                error="timeout",
            ),
            MQTTResult(
                broker="192.168.1.247",
                port=1883,
                success=True,
                connected=True,
                subscribed=True,
                published=True,
                received=True,
                round_trip_ms=12.5,
            ),
        ]
    )

    result = MQTTCheck(client=client).check(
        "192.168.1.247",
        retries=1,
    )

    assert result.healthy is True
    assert result.attempts == 2
    assert result.round_trip_ms == 12.5
    assert client.calls == 2


def test_mqtt_check_returns_last_failure() -> None:
    client = FakeMQTTClient(
        [
            MQTTResult(
                broker="192.168.1.247",
                port=1883,
                success=False,
                error="first",
            ),
            MQTTResult(
                broker="192.168.1.247",
                port=1883,
                success=False,
                error="second",
            ),
        ]
    )

    result = MQTTCheck(client=client).check(
        "192.168.1.247",
        retries=1,
    )

    assert result.healthy is False
    assert result.attempts == 2
    assert result.error == "second"


def test_mqtt_check_rejects_negative_retries() -> None:
    with pytest.raises(ValueError, match="retries"):
        MQTTCheck(client=FakeMQTTClient([])).check(
            "192.168.1.247",
            retries=-1,
        )
