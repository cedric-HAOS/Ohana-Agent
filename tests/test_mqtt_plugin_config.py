"""Tests for MQTT observation plugin configuration models."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from configuration.mqtt_plugin import MQTTPluginConfig


def test_mqtt_plugin_config_uses_safe_defaults() -> None:
    config = MQTTPluginConfig()

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


def test_mqtt_plugin_config_accepts_authentication_and_tls() -> None:
    config = MQTTPluginConfig.model_validate(
        {
            "authentication": {
                "username": " observer ",
                "password": "secret",
            },
            "tls": {
                "enabled": True,
                "ca_file": "/etc/ssl/certs/ohana-ca.pem",
                "insecure": False,
            },
        }
    )

    assert config.authentication.username == "observer"
    assert config.authentication.password == "secret"
    assert config.tls.ca_file == Path("/etc/ssl/certs/ohana-ca.pem")


def test_mqtt_plugin_config_rejects_password_without_username() -> None:
    with pytest.raises(ValidationError, match="requires a username"):
        MQTTPluginConfig.model_validate({"authentication": {"password": "secret"}})


def test_mqtt_plugin_config_rejects_wildcard_topic_prefix() -> None:
    with pytest.raises(ValidationError, match="wildcards"):
        MQTTPluginConfig(topic_prefix="ohana/+/check")


def test_mqtt_plugin_config_rejects_tls_options_when_disabled() -> None:
    with pytest.raises(ValidationError, match="require TLS"):
        MQTTPluginConfig.model_validate({"tls": {"enabled": False, "insecure": True}})


def test_mqtt_plugin_config_accepts_home_assistant_export_settings() -> None:
    config = MQTTPluginConfig.model_validate(
        {
            "home_assistant": {
                "enabled": False,
                "discovery_enabled": False,
                "discovery_prefix": "ha",
                "topic_prefix": "ohana-test",
                "heartbeat_seconds": 120,
            }
        }
    )

    assert config.home_assistant.enabled is False
    assert config.home_assistant.discovery_enabled is False
    assert config.home_assistant.discovery_prefix == "ha"
    assert config.home_assistant.topic_prefix == "ohana-test"
    assert config.home_assistant.heartbeat_seconds == 120


def test_mqtt_plugin_config_rejects_home_assistant_wildcards() -> None:
    with pytest.raises(ValidationError, match="wildcards"):
        MQTTPluginConfig.model_validate({"home_assistant": {"topic_prefix": "ohana/#"}})
