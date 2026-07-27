"""Tests for the MQTT plugin observation contract."""

import pytest

from plugin.plugin_context import PluginContext
from plugin.plugin_runtime import PluginState
from plugins.mqtt.mqtt_check_result import MQTTCheckResult
from plugins.mqtt.mqtt_config import (
    MQTTAuthenticationConfig,
    MQTTConfig,
    MQTTTLSConfig,
)
from plugins.mqtt.mqtt_plugin import MQTTPlugin


class FakeMQTTCheck:
    def __init__(self, result: MQTTCheckResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, object]]] = []

    def check(self, broker: str, **kwargs: object) -> MQTTCheckResult:
        self.calls.append((broker, kwargs))
        return self.result


def make_context() -> PluginContext:
    return PluginContext(
        event_bus=object(),
        scheduler=None,
        dispatcher=None,
        memory=None,
        capability_manager=None,
        configuration=None,
        runtime=None,
    )


def test_mqtt_plugin_returns_healthy_observer_result() -> None:
    check = FakeMQTTCheck(
        MQTTCheckResult(
            broker="192.168.1.247",
            port=1883,
            healthy=True,
            topic="ohana/agent/check/mqtt-primary/token",
            qos=1,
            client_id="ohana-agent-mqtt-primary-token",
            connected=True,
            subscribed=True,
            published=True,
            received=True,
            round_trip_ms=14.5,
            attempts=1,
        )
    )
    plugin = MQTTPlugin(
        check=check,
        config=MQTTConfig(
            timeout=4.0,
            retries=2,
            authentication=MQTTAuthenticationConfig(
                username="observer",
                password="secret",
            ),
            tls=MQTTTLSConfig(enabled=False),
        ),
    )

    result = plugin.execute(
        broker="192.168.1.247",
        port=1883,
        service_id="mqtt-primary",
    )

    assert result.success is True
    assert result.check == "mqtt.roundtrip"
    assert result.latency == 14.5
    assert result.metadata["received"] is True
    assert result.metadata["attempts"] == 1
    assert check.calls[0][0] == "192.168.1.247"
    assert check.calls[0][1]["service_id"] == "mqtt-primary"
    assert check.calls[0][1]["username"] == "observer"
    assert "password" in check.calls[0][1]


def test_mqtt_plugin_returns_failed_observer_result() -> None:
    plugin = MQTTPlugin(
        check=FakeMQTTCheck(
            MQTTCheckResult(
                broker="192.168.1.247",
                port=1883,
                healthy=False,
                connected=True,
                subscribed=True,
                published=True,
                received=False,
                attempts=2,
                error="round-trip timeout",
            )
        )
    )

    result = plugin.execute(
        broker="192.168.1.247",
        service_id="mqtt-primary",
    )

    assert result.success is False
    assert result.message == "round-trip timeout"
    assert result.metadata["error"] == "round-trip timeout"


def test_mqtt_plugin_registers_and_validates_arguments() -> None:
    plugin = MQTTPlugin()

    assert plugin.state is PluginState.LOADED

    plugin.register(make_context())

    assert plugin.state is PluginState.REGISTERED

    with pytest.raises(ValueError, match="broker"):
        plugin.execute(broker="")

    with pytest.raises(ValueError, match="port"):
        plugin.execute(broker="192.168.1.247", port=0)

    with pytest.raises(ValueError, match="service_id"):
        plugin.execute(broker="192.168.1.247", service_id="")
