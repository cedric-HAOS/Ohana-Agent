"""Tests for the Home Assistant telemetry YAML configuration loader."""

from pathlib import Path

from loader import HomeAssistantTelemetryConfigLoader, ShellyTelemetryConfigLoader


def test_home_assistant_telemetry_loader_reads_connection_policy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "home-assistant-telemetry.yaml"
    config_path.write_text(
        """
enabled: true
timeout: 4.0
retries: 1
interval_seconds: 300
maximum_age_seconds: 900
home_assistant_url: http://ha-green.ohana.lan:8123
access_token: secret
access_token_environment_variable: null
verify_tls: true
""".strip(),
        encoding="utf-8",
    )

    config = HomeAssistantTelemetryConfigLoader().load(config_path)

    assert config.home_assistant_url == "http://ha-green.ohana.lan:8123"
    assert config.maximum_age_seconds == 900


def test_legacy_loader_accepts_old_devices_section(tmp_path: Path) -> None:
    config_path = tmp_path / "shelly-telemetry.yaml"
    config_path.write_text(
        """
home_assistant_url: http://ha-green.ohana.lan:8123
access_token: secret
access_token_environment_variable: null
devices:
  - name: Cuisine
    power_entity_id: sensor.shelly_cuisine_power
    energy_entity_id: sensor.shelly_cuisine_energy
""".strip(),
        encoding="utf-8",
    )

    config = ShellyTelemetryConfigLoader().load(config_path)

    assert config.devices[0].name == "Cuisine"
    assert config.devices[0].power_entity_id == "sensor.shelly_cuisine_power"
