"""Tests for the MQTT observation plugin YAML loader."""

from pathlib import Path

from loader import MQTTConfigLoader


def test_mqtt_config_loader_loads_yaml(tmp_path: Path) -> None:
    path = tmp_path / "mqtt.yaml"
    path.write_text(
        """
timeout: 3.0
retries: 2
interval_seconds: 30
keepalive_seconds: 45
client_id_prefix: shikamaru
topic_prefix: ohana/tests
qos: 2
authentication:
  username: observer
  password: secret
tls:
  enabled: true
  ca_file: /etc/ssl/certs/ohana.pem
  insecure: false
""".strip(),
        encoding="utf-8",
    )

    config = MQTTConfigLoader().load(path)

    assert config.timeout == 3.0
    assert config.retries == 2
    assert config.interval_seconds == 30
    assert config.keepalive_seconds == 45
    assert config.client_id_prefix == "shikamaru"
    assert config.topic_prefix == "ohana/tests"
    assert config.qos == 2
    assert config.authentication.username == "observer"
    assert config.tls.enabled is True
