"""Tests for the NTP YAML configuration loader."""

from pathlib import Path

from loader import NTPConfigLoader


def test_ntp_config_loader_reads_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "ntp.yaml"
    config_path.write_text(
        """
timeout: 3.5
retries: 2
interval_seconds: 120
policy:
  maximum_offset_ms: 250.0
  maximum_stratum: 8
""".strip(),
        encoding="utf-8",
    )

    config = NTPConfigLoader().load(config_path)

    assert config.timeout == 3.5
    assert config.retries == 2
    assert config.interval_seconds == 120
    assert config.policy.maximum_offset_ms == 250.0
    assert config.policy.maximum_stratum == 8
