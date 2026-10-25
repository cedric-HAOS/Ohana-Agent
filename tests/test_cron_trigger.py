from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.scheduler import CronTrigger


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


def test_cron_trigger_fires_once_in_the_hour_repeated_by_the_clock_change() -> None:
    paris = ZoneInfo("Europe/Paris")
    trigger = CronTrigger("0 2 * * *", timezone=paris)
    first = datetime(2026, 10, 25, 0, 0, 2, tzinfo=UTC)  # 02:00 CEST
    second = datetime(2026, 10, 25, 1, 0, 2, tzinfo=UTC)  # 02:00 CET, an hour later

    assert trigger.is_due(first) is True
    trigger.mark_executed(first)

    assert trigger.is_due(second) is False
    # The next day is a new occurrence.
    assert trigger.is_due(datetime(2026, 10, 26, 1, 0, 2, tzinfo=UTC)) is True


def test_weekday_numbers_count_from_monday_not_like_crontab() -> None:
    sunday = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)
    saturday = datetime(2026, 10, 24, 2, 0, tzinfo=UTC)

    assert CronTrigger("0 2 * * 6").is_due(sunday) is True
    assert CronTrigger("0 2 * * 6").is_due(saturday) is False
    # In crontab(5) 0 is Sunday; here it is Monday, so this never fires on Sunday.
    assert CronTrigger("0 2 * * 0").is_due(sunday) is False


@pytest.mark.parametrize(
    "expression, day, due",
    [
        ("0 2 * * sun", datetime(2026, 10, 25, 2, 0, tzinfo=UTC), True),
        ("0 2 * * SUN", datetime(2026, 10, 25, 2, 0, tzinfo=UTC), True),
        ("0 2 * * sun", datetime(2026, 10, 24, 2, 0, tzinfo=UTC), False),
        ("0 2 * * mon", datetime(2026, 10, 26, 2, 0, tzinfo=UTC), True),
        ("0 2 * * mon-fri", datetime(2026, 10, 23, 2, 0, tzinfo=UTC), True),
        ("0 2 * * mon-fri", datetime(2026, 10, 24, 2, 0, tzinfo=UTC), False),
        ("0 2 * * sat,sun", datetime(2026, 10, 24, 2, 0, tzinfo=UTC), True),
    ],
)
def test_weekday_names_are_unambiguous(expression, day, due) -> None:
    assert CronTrigger(expression).is_due(day) is due


def test_crontab_sunday_seven_is_refused_not_silently_misread() -> None:
    with pytest.raises(ValueError, match="between 0 and 6"):
        CronTrigger("0 2 * * 7")
