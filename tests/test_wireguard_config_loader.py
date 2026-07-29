"""Tests for the Freebox WireGuard YAML configuration loader."""

from pathlib import Path

from loader import WireGuardConfigLoader


def test_wireguard_config_loader_reads_freebox_credentials(tmp_path: Path) -> None:
    config_path = tmp_path / "wireguard.yaml"
    config_path.write_text(
        """
enabled: true
timeout: 4.0
retries: 1
interval_seconds: 90
app_id: fr.ohana.agent
app_version: 1.8.1
app_token: secret
verify_tls: false
""".strip(),
        encoding="utf-8",
    )

    config = WireGuardConfigLoader().load(config_path)

    assert config.timeout == 4.0
    assert config.retries == 1
    assert config.interval_seconds == 90
    assert config.app_id == "fr.ohana.agent"
    assert config.app_token == "secret"
    assert config.verify_tls is False
