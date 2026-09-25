"""Europe/Paris is the only time zone Tsunade writes and returns."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AfterValidator

PARIS = ZoneInfo("Europe/Paris")


def to_paris(value: datetime) -> datetime:
    """Express an instant in Europe/Paris; naive values are taken as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(PARIS)


def paris_now() -> datetime:
    return datetime.now(PARIS)


def paris_iso(value: datetime | str) -> str:
    """Normalize a stored or computed instant to a Europe/Paris ISO string."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return to_paris(value).isoformat()


# Older rows mix UTC and Europe/Paris offsets; every returned model shows Paris.
ParisDatetime = Annotated[datetime, AfterValidator(to_paris)]
