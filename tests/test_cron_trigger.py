from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from scheduler import CronTrigger


def test_cron_trigger_rejects_invalid_expression() -> None:
    with pytest.raises(
        ValueError,
        match="cron expression must contain exactly five fields",
    ):
        CronTrigger("* * *")


def test_cron_trigger_matches_every_minute() -> None:
    trigger = CronTrigger("* * * * *")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    assert trigger.is_due(now) is True


def test_cron_trigger_matches_specific_hour_and_minute() -> None:
    trigger = CronTrigger("30 2 * * *")

    matching = datetime(2026, 1, 1, 2, 30, tzinfo=UTC)
    not_matching = datetime(2026, 1, 1, 2, 31, tzinfo=UTC)

    assert trigger.is_due(matching) is True
    assert trigger.is_due(not_matching) is False


def test_cron_trigger_computes_next_run() -> None:
    trigger = CronTrigger("30 2 * * *")
    after = datetime(2026, 1, 1, 2, 29, tzinfo=UTC)

    assert trigger.next_run_at(after) == datetime(2026, 1, 1, 2, 30, tzinfo=UTC)


def test_cron_trigger_supports_steps() -> None:
    trigger = CronTrigger("*/15 * * * *")

    assert trigger.is_due(datetime(2026, 1, 1, 12, 0, tzinfo=UTC)) is True
    assert trigger.is_due(datetime(2026, 1, 1, 12, 15, tzinfo=UTC)) is True
    assert trigger.is_due(datetime(2026, 1, 1, 12, 10, tzinfo=UTC)) is False


def test_cron_trigger_fires_only_once_during_matching_minute() -> None:
    trigger = CronTrigger("30 2 * * *")
    first_tick = datetime(2026, 1, 1, 2, 30, 1, tzinfo=UTC)

    assert trigger.is_due(first_tick) is True
    trigger.mark_executed(first_tick)

    assert trigger.is_due(datetime(2026, 1, 1, 2, 30, 59, tzinfo=UTC)) is False


def test_cron_trigger_interprets_configured_timezone() -> None:
    trigger = CronTrigger("0 5 * * *", timezone=ZoneInfo("Europe/Paris"))

    assert trigger.is_due(datetime(2026, 1, 1, 4, 0, tzinfo=UTC)) is True
    assert trigger.is_due(datetime(2026, 1, 1, 5, 0, tzinfo=UTC)) is False
