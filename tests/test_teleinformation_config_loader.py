"""Tests for the Téléinformation YAML configuration loader."""

from pathlib import Path

from loader import TeleinformationConfigLoader


def test_teleinformation_loader_reads_home_assistant_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "teleinformation.yaml"
    config_path.write_text(
        """
enabled: true
timeout: 4.0
retries: 2
interval_seconds: 60
maximum_age_seconds: 180
home_assistant_url: http://ha-green.ohana.lan:8123
access_token: secret
access_token_environment_variable: null
verify_tls: false
""".strip(),
        encoding="utf-8",
    )

    config = TeleinformationConfigLoader().load(config_path)

    assert config.enabled is True
    assert config.interval_seconds == 60
    assert config.maximum_age_seconds == 180
    assert config.home_assistant_url == "http://ha-green.ohana.lan:8123"
    assert config.access_token == "secret"
    assert config.access_token_environment_variable is None
    assert config.verify_tls is False
