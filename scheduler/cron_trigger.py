"""Cron trigger implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from scheduler.base_trigger import BaseTrigger


@dataclass
class CronTrigger(BaseTrigger):
    """Simple cron trigger supporting five fields: minute hour day month weekday."""

    expression: str

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
        self.weekdays = self._parse_field(fields[4], 0, 6)

    def next_run_at(self, after: datetime) -> datetime | None:
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

        for _ in range(366 * 24 * 60):
            if self._matches(candidate):
                return candidate

            candidate += timedelta(minutes=1)

        return None

    def is_due(self, now: datetime) -> bool:
        normalized = now.replace(second=0, microsecond=0)
        last_execution = self.last_executed_at
        already_executed = (
            last_execution is not None
            and last_execution.replace(second=0, microsecond=0) == normalized
        )
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
