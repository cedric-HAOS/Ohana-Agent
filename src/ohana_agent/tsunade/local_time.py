"""Europe/Paris is the only time zone Tsunade writes and returns."""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AfterValidator

PARIS = ZoneInfo("Europe/Paris")


def paris_instant(value: datetime) -> datetime:
    """Express an instant in Paris time with a fixed offset.

    Arithmetic on a ``ZoneInfo`` datetime is wall-clock arithmetic and drops
    ``fold``: across a clock change, or inside the hour it repeats, ``now + 5
    minutes`` or ``later - earlier`` is off by an hour, and such values never equal
    another zone's. A fixed offset keeps the displayed Paris time and makes every
    sum and difference exact (a sum keeps the offset it started with: pass it
    through ``to_paris`` again to label it with the Paris offset of its day). Use
    ``value.astimezone(PARIS)`` when a Paris calendar operation is needed
    (midnight, a given hour of the day).
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    offset = value.astimezone(PARIS).utcoffset()
    return value.astimezone(timezone(offset))  # type: ignore[arg-type]


def to_paris(value: datetime) -> datetime:
    """Express an instant in Europe/Paris; naive values are taken as UTC."""
    return paris_instant(value)


def paris_now() -> datetime:
    return paris_instant(datetime.now(UTC))


def paris_iso(value: datetime | str) -> str:
    """Normalize a stored or computed instant to a Europe/Paris ISO string."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return to_paris(value).isoformat()


# Older rows mix UTC and Europe/Paris offsets; every returned model shows Paris.
ParisDatetime = Annotated[datetime, AfterValidator(to_paris)]
