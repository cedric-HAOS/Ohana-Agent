from datetime import UTC, datetime, timedelta

import pytest

from ohana_agent.scheduler import IntervalTrigger


def test_interval_trigger_rejects_zero_interval() -> None:
    with pytest.raises(ValueError, match="interval must be greater than zero"):
        IntervalTrigger(timedelta(seconds=0))


def test_interval_trigger_is_not_due_before_first_execution() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = IntervalTrigger(timedelta(seconds=30))

    assert trigger.is_due(now) is False


def test_interval_trigger_next_run_without_start_date() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = IntervalTrigger(timedelta(seconds=30))

    assert trigger.next_run_at(now) == now + timedelta(seconds=30)


def test_interval_trigger_is_due_after_interval() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = IntervalTrigger(timedelta(seconds=30))

    trigger.mark_executed(now)

    assert trigger.is_due(now + timedelta(seconds=29)) is False
    assert trigger.is_due(now + timedelta(seconds=30)) is True


def test_interval_trigger_uses_start_date() -> None:
    start_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = IntervalTrigger(timedelta(minutes=5), start_at=start_at)

    assert trigger.is_due(start_at - timedelta(seconds=1)) is False
    assert trigger.is_due(start_at) is True
