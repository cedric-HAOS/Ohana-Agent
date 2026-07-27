"""Tests for the production network presence plugin configuration."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from bootstrap import _build_network_tasks
from loader import NetworkConfigLoader
from plugins.network.network_config import NetworkConfig, NetworkDeviceConfig


def test_production_network_configuration_uses_expected_settings() -> None:
    config = NetworkConfigLoader().load(Path("config/plugins/network.yaml"))

    assert config.enabled is True
    assert config.timeout == 1.0
    assert config.retries == 0
    assert config.interval_seconds == 60
    assert config.failure_threshold == 3


def test_network_tasks_are_spread_across_the_interval() -> None:
    start_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    config = NetworkConfig(
        devices=[
            NetworkDeviceConfig(
                name="router",
                label="Router",
                address="192.168.1.1",
            ),
            NetworkDeviceConfig(
                name="server",
                label="Server",
                address="192.168.1.10",
            ),
            NetworkDeviceConfig(
                name="access-point",
                label="Access point",
                address="192.168.1.99",
            ),
        ]
    )

    tasks = _build_network_tasks(
        network_config=config,
        interval_seconds=60,
        start_at=start_at,
    )

    assert [task.trigger.start_at for task in tasks] == [
        start_at,
        start_at + timedelta(seconds=20),
        start_at + timedelta(seconds=40),
    ]
