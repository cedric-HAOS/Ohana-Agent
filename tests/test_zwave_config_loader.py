"""Tests for the Z-Wave YAML configuration loader."""

from pathlib import Path

from loader import ZWaveConfigLoader


def test_zwave_config_loader_reads_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "zwave.yaml"
    config_path.write_text(
        """
enabled: true
timeout: 4.5
retries: 2
interval_seconds: 120
verify_tls: false
""".strip(),
        encoding="utf-8",
    )

    config = ZWaveConfigLoader().load(config_path)

    assert config.enabled is True
    assert config.timeout == 4.5
    assert config.retries == 2
    assert config.interval_seconds == 120
    assert config.verify_tls is False
