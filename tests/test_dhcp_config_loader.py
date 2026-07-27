from pathlib import Path

from loader.dhcp_config_loader import DHCPConfigLoader


def test_dhcp_config_loader_reads_yaml(tmp_path: Path) -> None:
    path = tmp_path / "dhcp.yaml"
    path.write_text(
        """enabled: true
check_service_active: false
timeout: 1.5
interval_seconds: 120
policy:
  maximum_pool_usage_percent: 80
""",
        encoding="utf-8",
    )

    config = DHCPConfigLoader().load(path)

    assert config.enabled is True
    assert config.check_service_active is False
    assert config.timeout == 1.5
    assert config.interval_seconds == 120
    assert config.policy.maximum_pool_usage_percent == 80
