"""Cron trigger implementation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from ohana_agent.scheduler.base_trigger import BaseTrigger


# Unlike the usual cron, the weekday field counts like Python's weekday(): 0 is
# Monday and 6 is Sunday (Sunday is 0 or 7 in crontab(5)). Every schedule saved
# by Vision uses these numbers. Names are unambiguous and accepted everywhere.
WEEKDAY_NAMES = {
    "mon": "0",
    "tue": "1",
    "wed": "2",
    "thu": "3",
    "fri": "4",
    "sat": "5",
    "sun": "6",
}
WEEKDAY_NAME = re.compile("|".join(WEEKDAY_NAMES), re.IGNORECASE)


@dataclass
class CronTrigger(BaseTrigger):
    """Cron trigger with five fields: minute hour day month weekday.

    The weekday is 0-6 for Monday-Sunday, or ``mon``..``sun`` (not crontab's
    Sunday-first numbering: ``0 2 * * 6`` runs on Sunday here, Saturday there).
    """

    expression: str
    timezone: tzinfo | None = None

    def __post_init__(self) -> None:
        super().__init__()

        fields = self.expression.split()
        if len(fields) != 5:
            msg = "cron expression must contain exactly five fields"
            raise ValueError(msg)

        self.minutes = self._parse_field(fields[0], 0, 59)
        self.hours = self._parse_field(fields[1], 0, 23)
        self.days = self._parse_field(fields[2], 1, 31)
        self.months = self._parse_field(fields[3], 1, 12)
        self.weekdays = self._parse_field(
            WEEKDAY_NAME.sub(lambda m: WEEKDAY_NAMES[m.group().lower()], fields[4]),
            0,
            6,
        )

    def next_run_at(self, after: datetime) -> datetime | None:
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        if self.timezone is not None:
            candidate = after.astimezone(self.timezone).replace(
                second=0, microsecond=0
            ) + timedelta(minutes=1)

        for _ in range(366 * 24 * 60):
            if self._matches(candidate):
                return candidate

            candidate += timedelta(minutes=1)

        return None

    def is_due(self, now: datetime) -> bool:
        normalized = now.replace(second=0, microsecond=0)
        if self.timezone is not None:
            normalized = now.astimezone(self.timezone).replace(second=0, microsecond=0)
        last_execution = self.last_executed_at
        already_executed = False
        if last_execution is not None:
            last = last_execution.replace(second=0, microsecond=0)
            if self.timezone is not None:
                # Compare wall-clock minutes: a time repeated by the autumn clock
                # change (02:00 twice) is the same cron occurrence, not a new one.
                last = last_execution.astimezone(self.timezone).replace(
                    second=0, microsecond=0, tzinfo=None
                )
                already_executed = last == normalized.replace(tzinfo=None)
            else:
                already_executed = last == normalized
        return self._matches(normalized) and not already_executed

    def _mark_executed(self, executed_at: datetime) -> None:
        pass

    def _matches(self, value: datetime) -> bool:
        return (
            value.minute in self.minutes
            and value.hour in self.hours
            and value.day in self.days
            and value.month in self.months
            and value.weekday() in self.weekdays
        )

    def _parse_field(self, field: str, minimum: int, maximum: int) -> set[int]:
        if field == "*":
            return set(range(minimum, maximum + 1))

        values: set[int] = set()

        for part in field.split(","):
            if "/" in part:
                base, step_raw = part.split("/", 1)
                step = int(step_raw)

                if step <= 0:
                    msg = "cron step must be greater than zero"
                    raise ValueError(msg)

                if base == "*":
                    start = minimum
                    end = maximum
                elif "-" in base:
                    start_raw, end_raw = base.split("-", 1)
                    start = int(start_raw)
                    end = int(end_raw)
                else:
                    start = int(base)
                    end = maximum

                values.update(range(start, end + 1, step))

            elif "-" in part:
                start_raw, end_raw = part.split("-", 1)
                values.update(range(int(start_raw), int(end_raw) + 1))

            else:
                values.add(int(part))

        if not values or min(values) < minimum or max(values) > maximum:
            msg = f"cron field values must be between {minimum} and {maximum}"
            raise ValueError(msg)

        return values
