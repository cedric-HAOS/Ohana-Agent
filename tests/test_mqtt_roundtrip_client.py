"""Tests for the active MQTT round-trip client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from plugins.mqtt.mqtt_client import MQTTRoundTripClient


@dataclass
class FakeMessage:
    topic: str
    payload: bytes


@dataclass
class FakePublishInfo:
    rc: int = 0


class FakePahoClient:
    def __init__(self) -> None:
        self.on_connect = None
        self.on_subscribe = None
        self.on_message = None
        self.connect_reason_code = 0
        self.subscribe_result = 0
        self.publish_result = 0
        self.deliver_message = True
        self.calls: list[tuple[Any, ...]] = []
        self.username: str | None = None
        self.password: str | None = None
        self.ca_file: str | None = None
        self.tls_insecure = False

    def username_pw_set(self, username: str, password: str | None) -> None:
        self.username = username
        self.password = password

    def tls_set(self, *, ca_certs: str | None) -> None:
        self.ca_file = ca_certs

    def tls_insecure_set(self, insecure: bool) -> None:
        self.tls_insecure = insecure

    def connect(self, broker: str, port: int, *, keepalive: int) -> int:
        self.calls.append(("connect", broker, port, keepalive))
        return 0

    def loop_start(self) -> None:
        self.calls.append(("loop_start",))
        assert self.on_connect is not None
        self.on_connect(self, None, None, self.connect_reason_code, None)

    def subscribe(self, topic: str, *, qos: int) -> tuple[int, int]:
        self.calls.append(("subscribe", topic, qos))
        assert self.on_subscribe is not None
        self.on_subscribe(self, None, 1, [qos], None)
        return self.subscribe_result, 1

    def publish(
        self,
        topic: str,
        payload: bytes,
        *,
        qos: int,
        retain: bool,
    ) -> FakePublishInfo:
        self.calls.append(("publish", topic, payload, qos, retain))

        if self.deliver_message:
            assert self.on_message is not None
            self.on_message(self, None, FakeMessage(topic=topic, payload=payload))

        return FakePublishInfo(rc=self.publish_result)

    def unsubscribe(self, topic: str) -> None:
        self.calls.append(("unsubscribe", topic))

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))

    def loop_stop(self) -> None:
        self.calls.append(("loop_stop",))


def test_mqtt_roundtrip_client_succeeds() -> None:
    fake_client = FakePahoClient()
    clock_values = iter([10.0, 10.025])
    client = MQTTRoundTripClient(
        client_factory=lambda client_id: fake_client,
        monotonic_clock=lambda: next(clock_values),
        token_factory=lambda: "abc123",
    )

    result = client.roundtrip(
        "192.168.1.247",
        port=1883,
        service_id="mqtt-primary",
        topic_prefix="ohana/agent/check",
        qos=1,
    )

    assert result.success is True
    assert result.broker == "192.168.1.247"
    assert result.topic == "ohana/agent/check/mqtt-primary/abc123"
    assert result.client_id == "ohana-agent-mqtt-primary-abc123"
    assert result.connected is True
    assert result.subscribed is True
    assert result.published is True
    assert result.received is True
    assert result.round_trip_ms == pytest.approx(25.0)
    assert ("disconnect",) in fake_client.calls
    assert ("loop_stop",) in fake_client.calls


def test_mqtt_roundtrip_client_configures_authentication_and_tls() -> None:
    fake_client = FakePahoClient()
    client = MQTTRoundTripClient(
        client_factory=lambda client_id: fake_client,
        monotonic_clock=iter([1.0, 1.01]).__next__,
        token_factory=lambda: "token",
    )

    result = client.roundtrip(
        "mqtt.ohana.lan",
        port=8883,
        username="observer",
        password="secret",
        tls_enabled=True,
        ca_file="/etc/ssl/certs/ohana-ca.pem",
        tls_insecure=False,
    )

    assert result.success is True
    assert result.tls_enabled is True
    assert fake_client.username == "observer"
    assert fake_client.password == "secret"
    assert fake_client.ca_file == "/etc/ssl/certs/ohana-ca.pem"
    assert fake_client.tls_insecure is False


def test_mqtt_roundtrip_client_reports_connection_rejection() -> None:
    fake_client = FakePahoClient()
    fake_client.connect_reason_code = 5
    client = MQTTRoundTripClient(
        client_factory=lambda client_id: fake_client,
        token_factory=lambda: "token",
    )

    result = client.roundtrip("192.168.1.247", timeout=0.01)

    assert result.success is False
    assert result.connected is False
    assert "rejected" in (result.error or "")


def test_mqtt_roundtrip_client_reports_receive_timeout() -> None:
    fake_client = FakePahoClient()
    fake_client.deliver_message = False
    client = MQTTRoundTripClient(
        client_factory=lambda client_id: fake_client,
        token_factory=lambda: "token",
    )

    result = client.roundtrip("192.168.1.247", timeout=0.001)

    assert result.success is False
    assert result.connected is True
    assert result.subscribed is True
    assert result.published is True
    assert result.received is False
    assert "round-trip" in (result.error or "")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"broker": ""}, "broker"),
        ({"broker": "host", "port": 0}, "port"),
        ({"broker": "host", "timeout": 0}, "timeout"),
        ({"broker": "host", "qos": 3}, "qos"),
        ({"broker": "host", "topic_prefix": "ohana/#"}, "wildcards"),
    ],
)
def test_mqtt_roundtrip_client_validates_arguments(
    kwargs: dict[str, Any],
    message: str,
) -> None:
    client = MQTTRoundTripClient(client_factory=lambda client_id: FakePahoClient())

    with pytest.raises(ValueError, match=message):
        client.roundtrip(**kwargs)
