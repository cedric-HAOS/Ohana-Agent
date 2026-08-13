from pathlib import Path

import pytest

from builder import BackupConfigurationBuilder
from configuration.backup import BackupPluginConfig
from loader import BackupConfigLoader


def test_backup_example_configuration_builds_three_targets() -> None:
    plugin_config = BackupConfigLoader().load(
        Path("config/plugins/backup.example.yaml")
    )

    runtime = BackupConfigurationBuilder().build(plugin_config)

    assert plugin_config.enabled is False
    assert [target.id for target in runtime.targets] == [
        "ha-01",
        "linky-01",
        "zwave-01",
    ]
    assert runtime.temporary_directory == "/run/ohana-agent/backup"
    assert runtime.require_tmpfs is True
    assert runtime.infra_01.remote_retention_count == 0
    assert runtime.infra_01.age_recipient_file.endswith("infra-01.agepub")
    assert runtime.infra_01.age_identity_file.endswith("infra-01.agekey")
    assert runtime.targets[2].pre_backup_action is not None
    assert runtime.targets[2].pre_backup_action.service == ("ohana_backup_zwave_nvm")


def test_enabled_backup_configuration_requires_targets() -> None:
    with pytest.raises(ValueError, match="requires at least one target"):
        BackupPluginConfig.model_validate({"enabled": True})


def test_backup_configuration_rejects_duplicate_target_ids() -> None:
    target = {
        "id": "ha-01",
        "label": "HA-01",
        "url": "http://ha-01:8123",
        "token_environment_variable": "HA_TOKEN",
        "password_environment_variable": "HA_PASSWORD",
        "schedule": "0 2 * * *",
    }
    with pytest.raises(ValueError, match="target ids must be unique"):
        BackupPluginConfig.model_validate({"targets": [target, target]})


def test_backup_configuration_rejects_local_rclone_destination() -> None:
    with pytest.raises(ValueError, match="named remote"):
        BackupPluginConfig.model_validate({"rclone_remote": "/var/lib/backups"})


def test_backup_configuration_rejects_invalid_infra_remote_retention() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        BackupPluginConfig.model_validate({"infra_01": {"remote_retention_count": -1}})
