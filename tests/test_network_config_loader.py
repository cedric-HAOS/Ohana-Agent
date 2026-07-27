"""Tests for the network presence YAML configuration loader."""

from pathlib import Path

from loader import NetworkConfigLoader


def test_network_config_loader_reads_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "network.yaml"
    config_path.write_text(
        """
enabled: true
timeout: 1.5
retries: 2
interval_seconds: 120
failure_threshold: 4
""".strip(),
        encoding="utf-8",
    )

    config = NetworkConfigLoader().load(config_path)

    assert config.enabled is True
    assert config.timeout == 1.5
    assert config.retries == 2
    assert config.interval_seconds == 120
    assert config.failure_threshold == 4
