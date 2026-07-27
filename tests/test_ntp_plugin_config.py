"""Tests for declarative NTP plugin configuration."""

import pytest
from pydantic import ValidationError

from configuration.ntp import NTPPluginConfig


def test_ntp_plugin_config_uses_safe_defaults() -> None:
    config = NTPPluginConfig()

    assert config.timeout == 2.0
    assert config.retries == 1
    assert config.interval_seconds == 60
    assert config.policy.maximum_offset_ms == 1000.0
    assert config.policy.maximum_stratum == 15


def test_ntp_plugin_config_rejects_invalid_policy() -> None:
    with pytest.raises(ValidationError):
        NTPPluginConfig.model_validate(
            {
                "policy": {
                    "maximum_offset_ms": 0,
                    "maximum_stratum": 16,
                }
            }
        )
