"""Thread-safe storage for frames pushed directly by teleinfo2mqtt."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Any


@dataclass(frozen=True, slots=True)
class TeleinformationFrame:
    """One validated teleinformation frame received by Ohana-Agent."""

    source: str
    meter_id: str
    values: dict[str, float | int | str]
    raw_values: dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class TeleinformationFrameStore:
    """Keep the latest direct frame for each source and meter."""

    def __init__(self) -> None:
        self._frames: dict[tuple[str, str], TeleinformationFrame] = {}
        self._lock = RLock()

    def put(
        self,
        *,
        source: str,
        meter_id: str,
        frame: dict[str, Any],
        received_at: datetime | None = None,
    ) -> TeleinformationFrame:
        """Validate and store one teleinfo2mqtt frame."""
        normalized_source = self._required_text(source, "source")
        normalized_meter_id = self._required_text(meter_id, "meter_id")
        values: dict[str, float | int | str] = {}

        for label, raw_entry in frame.items():
            if not isinstance(label, str) or not label.strip():
                continue
            value = self._extract_value(raw_entry)
            if value is not None:
                values[label.strip().upper()] = value

        stored = TeleinformationFrame(
            source=normalized_source,
            meter_id=normalized_meter_id,
            values=values,
            raw_values=dict(frame),
            received_at=(received_at or datetime.now(UTC)).astimezone(UTC),
        )
        with self._lock:
            self._frames[(normalized_source, normalized_meter_id)] = stored
        return stored

    def get(self, *, source: str, meter_id: str) -> TeleinformationFrame | None:
        """Return the latest frame for one source and meter."""
        with self._lock:
            return self._frames.get((source.strip(), meter_id.strip()))

    @staticmethod
    def _extract_value(entry: object) -> float | int | str | None:
        if isinstance(entry, dict):
            entry = entry.get("value", entry.get("raw"))

        if isinstance(entry, bool) or entry is None:
            return None
        if isinstance(entry, (int, float, str)):
            return entry
        return None

    @staticmethod
    def _required_text(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string.")
        return value.strip()
