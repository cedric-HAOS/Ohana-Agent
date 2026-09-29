"""Phase 5: last useful activity of the Agent's critical internal components.

Each component records a beat when it completes real work; a component silent
for longer than its declared bound is "stale". This is deliberately not a
process introspection: it only tells whether each part still works. A frozen
main loop stops host health reporting too, so that case is left to Vision
noticing the Agent's silence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from time import monotonic
from typing import Any

from ohana_agent.tsunade.local_time import paris_now


@dataclass(slots=True)
class _Component:
    label: str
    max_silence_seconds: float
    declared_at: float
    last_beat: float | None = None
    last_activity_at: datetime | None = None


class AgentVitals:
    """Thread-safe registry of component beats, read by host health."""

    def __init__(
        self,
        *,
        monotonic_clock: Callable[[], float] = monotonic,
        wall_clock: Callable[[], datetime] = paris_now,
    ) -> None:
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._components: dict[str, _Component] = {}
        self._lock = Lock()

    def declare(
        self, component: str, *, label: str, max_silence_seconds: float
    ) -> None:
        """Register one component; it has one bound to show a first beat."""
        if max_silence_seconds <= 0:
            raise ValueError("max_silence_seconds must be greater than zero.")
        with self._lock:
            self._components[component] = _Component(
                label=label,
                max_silence_seconds=max_silence_seconds,
                declared_at=self._monotonic_clock(),
            )

    def beat(self, component: str) -> None:
        """Record useful activity; undeclared components are ignored."""
        now = self._monotonic_clock()
        at = self._wall_clock()
        with self._lock:
            entry = self._components.get(component)
            if entry is not None:
                entry.last_beat = now
                entry.last_activity_at = at

    def beater(self, component: str) -> Callable[[], None]:
        """Return a callback recording beats for ``component``."""
        return lambda: self.beat(component)

    def snapshot(self) -> tuple[dict[str, Any], ...]:
        """Describe every component in declaration order."""
        now = self._monotonic_clock()
        with self._lock:
            return tuple(
                self._describe(name, entry, now)
                for name, entry in self._components.items()
            )

    @staticmethod
    def _describe(name: str, entry: _Component, now: float) -> dict[str, Any]:
        beaten = entry.last_beat is not None
        reference = entry.last_beat if beaten else entry.declared_at
        silence = max(now - reference, 0.0)
        if silence > entry.max_silence_seconds:
            state = "stale"
        elif not beaten:
            state = "waiting"
        else:
            state = "active"
        return {
            "component": name,
            "label": entry.label,
            "state": state,
            "last_activity_at": (
                entry.last_activity_at.isoformat()
                if entry.last_activity_at is not None
                else None
            ),
            "silence_seconds": int(silence) if beaten else None,
            "max_silence_seconds": int(entry.max_silence_seconds),
        }


def stale_components(snapshot: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    """Return the names of the components past their silence bound."""
    return tuple(item["component"] for item in snapshot if item["state"] == "stale")


def silent_agent_components(vitals: AgentVitals) -> tuple[str, ...]:
    """Silent components that mean the Agent itself no longer works.

    Delivery to Vision is left out: Vision's own outage has its incident and
    must not make Home Assistant believe the Agent is frozen.
    """
    return tuple(
        name
        for name in stale_components(vitals.snapshot())
        if name != "vision_delivery"
    )
