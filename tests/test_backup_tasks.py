from bootstrap import _build_backup_tasks
from plugins.backup.backup_config import BackupConfig, BackupTarget
from scheduler import CronTrigger


def test_backup_tasks_are_staggered_and_target_devices() -> None:
    config = BackupConfig(
        targets=(
            BackupTarget(
                id="ha-01",
                label="HA-01",
                url="http://ha-01:8123",
                token_environment_variable="HA_TOKEN",
                password_environment_variable="HA_PASSWORD",
                schedule="0 2 * * *",
            ),
            BackupTarget(
                id="linky-01",
                label="LINKY-01",
                url="http://linky-01:8123",
                token_environment_variable="LINKY_TOKEN",
                password_environment_variable="LINKY_PASSWORD",
                schedule="0 3 * * *",
                enabled=False,
            ),
        )
    )

    tasks = _build_backup_tasks(backup_config=config)

    assert [task.id for task in tasks] == ["backup.run:ha-01"]
    assert all(task.command == "backup.run" for task in tasks)
    assert all(isinstance(task.trigger, CronTrigger) for task in tasks)
    assert tasks[0].arguments == {
        "target_id": "ha-01",
        "device_id": "ha-01",
        "node_id": "ha-01",
    }
    assert tasks[0].metadata["schedule"] == "0 2 * * *"
    assert "node_id" not in tasks[0].metadata
