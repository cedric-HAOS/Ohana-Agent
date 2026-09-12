from ohana_agent.scheduler import SchedulerStatistics


def test_scheduler_statistics_defaults() -> None:
    statistics = SchedulerStatistics()

    assert statistics.tasks_executed == 0
    assert statistics.tasks_failed == 0
    assert statistics.tick_count == 0


def test_scheduler_statistics_records_tick() -> None:
    statistics = SchedulerStatistics()

    statistics.record_tick()

    assert statistics.tick_count == 1


def test_scheduler_statistics_records_successful_task_result() -> None:
    statistics = SchedulerStatistics()

    statistics.record_task_result(success=True)

    assert statistics.tasks_executed == 1
    assert statistics.tasks_failed == 0


def test_scheduler_statistics_records_failed_task_result() -> None:
    statistics = SchedulerStatistics()

    statistics.record_task_result(success=False)

    assert statistics.tasks_executed == 0
    assert statistics.tasks_failed == 1
