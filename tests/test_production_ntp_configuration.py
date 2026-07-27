"""Tests for the production NTP plugin configuration."""

from pathlib import Path

from loader import NTPConfigLoader


def test_production_ntp_configuration_uses_expected_policy() -> None:
    config = NTPConfigLoader().load(Path("config/plugins/ntp.yaml"))

    assert config.timeout == 2.0
    assert config.retries == 1
    assert config.interval_seconds == 60
    assert config.policy.maximum_offset_ms == 1000.0
    assert config.policy.maximum_stratum == 15
