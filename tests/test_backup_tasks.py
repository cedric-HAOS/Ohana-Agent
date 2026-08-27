from datetime import UTC, datetime

from bootstrap import (
    _build_backup_tasks,
    _build_log_analysis_tasks,
    _build_wake_dispatch_tasks,
)
from configuration.administration import (
    DistributedJobsConfig,
    DistributedLogAnalysisConfig,
)
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


def test_backup_tasks_accept_weekly_and_monthly_periodicity() -> None:
    config = BackupConfig(
        targets=(
            BackupTarget(
                id="ha-01",
                label="HA-01",
                url="http://ha-01:8123",
                token_environment_variable="HA_TOKEN",
                password_environment_variable="HA_PASSWORD",
                schedule="0 2 * * 0",
            ),
            BackupTarget(
                id="linky-01",
                label="LINKY-01",
                url="http://linky-01:8123",
                token_environment_variable="LINKY_TOKEN",
                password_environment_variable="LINKY_PASSWORD",
                schedule="30 3 1 * *",
            ),
        )
    )

    tasks = _build_backup_tasks(backup_config=config)

    assert [task.metadata["schedule"] for task in tasks] == [
        "0 2 * * 0",
        "30 3 1 * *",
    ]
    assert all(isinstance(task.trigger, CronTrigger) for task in tasks)


def test_log_analysis_task_uses_configured_schedule_and_sources() -> None:
    config = DistributedLogAnalysisConfig(
        enabled=True,
        schedule="30 6 * * *",
        sources=("ha-01", "zwave-01"),
        window_hours=12,
        max_bytes_per_source=1048576,
        timeout_seconds=600,
    )

    tasks = _build_log_analysis_tasks(logs_config=config)

    assert [task.id for task in tasks] == ["tsunade.logs.health_check"]
    assert isinstance(tasks[0].trigger, CronTrigger)
    assert tasks[0].arguments == {
        "sources": ["ha-01", "zwave-01"],
        "window_hours": 12,
        "max_bytes_per_source": 1048576,
        "timeout_seconds": 600,
    }
    assert tasks[0].metadata["schedule"] == "30 6 * * *"


def test_wake_dispatcher_runs_when_distributed_jobs_are_enabled() -> None:
    config = DistributedJobsConfig(enabled=True)

    tasks = _build_wake_dispatch_tasks(
        jobs_config=config,
        start_at=datetime(2026, 8, 27, tzinfo=UTC),
    )

    assert [task.id for task in tasks] == ["tsunade.wake.dispatch"]
    assert tasks[0].command == "jobs.wake.dispatch"
    assert tasks[0].metadata["managed_by"] == "tsunade-wake"
