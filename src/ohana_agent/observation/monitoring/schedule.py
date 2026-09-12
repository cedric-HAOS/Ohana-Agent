"""Evaluate optional monitoring periods declared on topology devices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(frozen=True, slots=True)
class MonitoringDecision:
    """Result of a monitoring schedule evaluation."""

    active: bool
    reason: str | None = None
    next_activation: datetime | None = None
    grace_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class _Period:
    days: frozenset[int]
    start: time
    end: time


@dataclass(frozen=True, slots=True)
class _Schedule:
    timezone: ZoneInfo
    periods: tuple[_Period, ...]
    startup_grace_seconds: int


class MonitoringScheduleRegistry:
    """Thread-safe schedules indexed by infrastructure node identifier."""

    def __init__(self) -> None:
        self._schedules: dict[str, _Schedule] = {}
        self._lock = RLock()

    def replace_from_infrastructure(self, configuration: Any) -> None:
        """Replace schedules from an InfrastructureConfig-like object."""
        schedules: dict[str, _Schedule] = {}
        topology = getattr(configuration, "topology", None)

        if topology is not None:
            for device in getattr(topology, "devices", ()):
                node_id = getattr(device, "node", None)
                device_id = getattr(device, "id", None)
                metadata = getattr(device, "metadata", {})

                if not isinstance(metadata, dict):
                    continue

                raw_schedule = metadata.get("monitoring_schedule")
                schedule = self._parse_schedule(raw_schedule)

                if schedule is not None:
                    if isinstance(device_id, str) and device_id.strip():
                        schedules[device_id.strip()] = schedule
                    if isinstance(node_id, str) and node_id.strip():
                        schedules[node_id.strip()] = schedule

        with self._lock:
            self._schedules = schedules

    def decision(self, node_id: str | None, now: datetime) -> MonitoringDecision:
        """Return whether monitoring is active for one node at ``now``."""
        if not isinstance(node_id, str) or not node_id.strip():
            return MonitoringDecision(active=True)

        with self._lock:
            schedule = self._schedules.get(node_id.strip())

        if schedule is None:
            return MonitoringDecision(active=True)

        local_now = now.astimezone(schedule.timezone)
        active_start = self._active_period_start(schedule, local_now)

        if active_start is not None:
            grace_until = active_start + timedelta(
                seconds=schedule.startup_grace_seconds
            )

            if local_now < grace_until:
                return MonitoringDecision(
                    active=False,
                    reason="Délai de démarrage de la surveillance.",
                    next_activation=grace_until,
                    grace_until=grace_until,
                )

            return MonitoringDecision(active=True)

        next_activation = self._next_activation(schedule, local_now)
        return MonitoringDecision(
            active=False,
            reason="Surveillance suspendue en dehors de la plage horaire.",
            next_activation=next_activation,
        )

    @classmethod
    def validate_payload(cls, payload: object) -> None:
        """Raise ValueError when a declared monitoring schedule is invalid."""
        if payload is None:
            return
        cls._parse_schedule(payload, strict=True)

    @classmethod
    def _parse_schedule(
        cls,
        payload: object,
        *,
        strict: bool = False,
    ) -> _Schedule | None:
        if payload in (None, {}, False):
            return None

        if not isinstance(payload, dict):
            if strict:
                raise ValueError("monitoring_schedule must be a mapping.")
            return None

        if payload.get("enabled", True) is False:
            return None

        timezone_name = payload.get("timezone", "Europe/Paris")
        if not isinstance(timezone_name, str) or not timezone_name.strip():
            raise ValueError("monitoring_schedule.timezone must not be empty.")

        try:
            timezone = ZoneInfo(timezone_name.strip())
        except ZoneInfoNotFoundError as error:
            raise ValueError(
                f"Unknown monitoring schedule timezone: {timezone_name}"
            ) from error

        raw_grace = payload.get("startup_grace_seconds", 0)
        if isinstance(raw_grace, bool) or not isinstance(raw_grace, int):
            raise ValueError(
                "monitoring_schedule.startup_grace_seconds must be an integer."
            )
        if raw_grace < 0 or raw_grace > 86_400:
            raise ValueError(
                "monitoring_schedule.startup_grace_seconds must be between 0 and 86400."
            )

        raw_periods = payload.get("periods")
        if not isinstance(raw_periods, list) or not raw_periods:
            raise ValueError(
                "monitoring_schedule.periods must contain at least one period."
            )

        periods = tuple(cls._parse_period(item) for item in raw_periods)
        return _Schedule(
            timezone=timezone,
            periods=periods,
            startup_grace_seconds=raw_grace,
        )

    @staticmethod
    def _parse_period(payload: object) -> _Period:
        if not isinstance(payload, dict):
            raise ValueError("Each monitoring period must be a mapping.")

        raw_days = payload.get("days")
        if not isinstance(raw_days, list) or not raw_days:
            raise ValueError("Each monitoring period must define days.")

        days: set[int] = set()
        for raw_day in raw_days:
            if not isinstance(raw_day, str):
                raise ValueError("Monitoring period days must be strings.")
            day = _DAY_NAMES.get(raw_day.strip().lower())
            if day is None:
                raise ValueError(f"Unknown monitoring period day: {raw_day}")
            days.add(day)

        return _Period(
            days=frozenset(days),
            start=MonitoringScheduleRegistry._parse_time(payload.get("start"), "start"),
            end=MonitoringScheduleRegistry._parse_time(payload.get("end"), "end"),
        )

    @staticmethod
    def _parse_time(value: object, field_name: str) -> time:
        if not isinstance(value, str):
            raise ValueError(f"Monitoring period {field_name} must use HH:MM.")
        try:
            parsed = time.fromisoformat(value.strip())
        except ValueError as error:
            raise ValueError(
                f"Monitoring period {field_name} must use HH:MM."
            ) from error
        return parsed.replace(second=0, microsecond=0)

    @staticmethod
    def _period_bounds(
        schedule: _Schedule,
        period: _Period,
        local_now: datetime,
        day_offset: int,
    ) -> tuple[datetime, datetime] | None:
        date = local_now.date() + timedelta(days=day_offset)
        weekday = date.weekday()

        if weekday not in period.days:
            return None

        start = datetime.combine(date, period.start, schedule.timezone)
        end = datetime.combine(date, period.end, schedule.timezone)

        if period.end <= period.start:
            end += timedelta(days=1)

        return start, end

    @classmethod
    def _active_period_start(
        cls,
        schedule: _Schedule,
        local_now: datetime,
    ) -> datetime | None:
        for day_offset in (-1, 0):
            for period in schedule.periods:
                bounds = cls._period_bounds(schedule, period, local_now, day_offset)
                if bounds is None:
                    continue
                start, end = bounds
                if start <= local_now < end:
                    return start
        return None

    @classmethod
    def _next_activation(
        cls,
        schedule: _Schedule,
        local_now: datetime,
    ) -> datetime | None:
        candidates: list[datetime] = []
        for day_offset in range(0, 8):
            for period in schedule.periods:
                bounds = cls._period_bounds(schedule, period, local_now, day_offset)
                if bounds is None:
                    continue
                start, _end = bounds
                start += timedelta(seconds=schedule.startup_grace_seconds)
                if start > local_now:
                    candidates.append(start)
        return min(candidates, default=None)
