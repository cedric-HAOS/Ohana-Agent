from plugins.backup.backup_config import BackupConfig, BackupTarget
from plugins.backup.backup_coordinator import (
    BackupExecutionError,
    BackupExecutionResult,
)
from plugins.backup.backup_plugin import BackupPlugin


class SuccessfulCoordinator:
    def run(self, target: BackupTarget) -> BackupExecutionResult:
        return BackupExecutionResult(
            target_id=target.id,
            backup_slug="slug",
            backup_name="Ohana-ha-01-date",
            remote_path="icloud:Ohana/Backups/ha-01/archive.tar",
            size_bytes=42,
            sha256="abc",
            deleted_local_backups=1,
        )


class FailingCoordinator:
    def run(self, target: BackupTarget) -> BackupExecutionResult:
        del target
        raise BackupExecutionError("upload", "rclone failed")


def make_config() -> BackupConfig:
    return BackupConfig(
        targets=(
            BackupTarget(
                id="ha-01",
                label="HA-01",
                url="http://ha-01:8123",
                token_environment_variable="HA_TOKEN",
                password_environment_variable="HA_PASSWORD",
                schedule="0 2 * * *",
            ),
        )
    )


def test_backup_plugin_publishes_validated_success_metadata() -> None:
    plugin = BackupPlugin(
        config=make_config(),
        coordinator=SuccessfulCoordinator(),
    )

    result = plugin.execute(target_id="ha-01")

    assert result.success is True
    assert result.check == "backup.run"
    assert result.metadata["target_type"] == "device"
    assert result.metadata["device_id"] == "ha-01"
    assert result.metadata["stage"] == "completed"
    assert result.metadata["size_bytes"] == 42


def test_backup_plugin_turns_coordinator_failure_into_observation() -> None:
    plugin = BackupPlugin(
        config=make_config(),
        coordinator=FailingCoordinator(),
    )

    result = plugin.execute(target_id="ha-01")

    assert result.success is False
    assert result.metadata["stage"] == "upload"
    assert result.metadata["error"] == "rclone failed"
