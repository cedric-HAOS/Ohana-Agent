"""Tests for the production MQTT observation plugin configuration."""

from pathlib import Path

from loader import MQTTConfigLoader


def test_production_mqtt_configuration_uses_expected_settings() -> None:
    config = MQTTConfigLoader().load(Path("config/plugins/mqtt.yaml"))

    assert config.timeout == 5.0
    assert config.retries == 1
    assert config.interval_seconds == 60
    assert config.keepalive_seconds == 60
    assert config.client_id_prefix == "ohana-agent"
    assert config.topic_prefix == "ohana/agent/check"
    assert config.qos == 1
    assert config.authentication.username is None
    assert config.tls.enabled is False
    assert config.home_assistant.enabled is True
    assert config.home_assistant.discovery_enabled is True
    assert config.home_assistant.discovery_prefix == "homeassistant"
    assert config.home_assistant.topic_prefix == "ohana"
    assert config.home_assistant.heartbeat_seconds == 60
