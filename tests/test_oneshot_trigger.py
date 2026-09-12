from datetime import UTC, datetime, timedelta

from ohana_agent.scheduler import OneShotTrigger


def test_oneshot_trigger_is_due_at_run_date() -> None:
    run_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = OneShotTrigger(run_at)

    assert trigger.is_due(run_at - timedelta(seconds=1)) is False
    assert trigger.is_due(run_at) is True


def test_oneshot_trigger_is_not_due_after_execution() -> None:
    run_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = OneShotTrigger(run_at)

    trigger.mark_executed(run_at)

    assert trigger.is_due(run_at + timedelta(hours=1)) is False


def test_oneshot_trigger_next_run_is_none_after_execution() -> None:
    run_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = OneShotTrigger(run_at)

    trigger.mark_executed(run_at)

    assert trigger.next_run_at(run_at) is None
