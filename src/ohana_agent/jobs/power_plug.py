"""When Katsuyu's PC is powered: switch a smart plug on before a wake, off after.

The plug is switched on just before a Wake-on-LAN and off once the PC has shut
down, so a power surge finds the PC unplugged almost all the time. The plug
itself is a plugin (``power_plug``); this module only decides. Every path fails
open: if the plug cannot be read or commanded, Ohana behaves exactly as it did
without a plug (Wake-on-LAN only) and never cuts power it cannot justify.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

LOGGER = logging.getLogger(__name__)

# Reasons the plug may be cut. Only "shutdown_started" cuts without a watt reading.
REASON_SHUTDOWN_STARTED = "shutdown_started"


class PowerPlugError(RuntimeError):
    """The plug could not be read or commanded (never carries the token)."""


@dataclass(frozen=True, slots=True)
class PlugReading:
    """What the plug reports right now."""

    is_on: bool
    power_watts: float | None = None


@dataclass(frozen=True, slots=True)
class PlugPolicy:
    """The timings the owner configured for the plug."""

    boot_delay_seconds: int = 15
    shutdown_grace_seconds: int = 300
    idle_watts: float = 5.0
    idle_confirm_seconds: int = 30
    poll_seconds: int = 15


@dataclass(frozen=True, slots=True)
class PlugCutCandidate:
    """The PC looks finished for this reason, since this moment."""

    reason: str
    since: datetime


@dataclass(frozen=True, slots=True)
class PlugWake:
    """What happened to the plug when a wake was requested."""

    status: str  # disabled | already_on | turned_on | failed | unreadable
    delay_seconds: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PlugCut:
    """Outcome of one attempt to cut the plug after a cycle."""

    outcome: str  # cut | already_off | failed
    reason: str
    detail: dict[str, Any]


@dataclass(slots=True)
class PendingWake:
    """A Wake-on-LAN waiting for the PC to receive power."""

    worker_id: str
    mac_address: str
    trigger: str
    due_at: datetime


class PowerPlug(Protocol):
    """The three things Ohana does with the plug."""

    def read(self) -> PlugReading: ...

    def turn_on(self) -> None: ...

    def turn_off(self) -> None: ...


class PlugStore(Protocol):
    """Durable "Ohana switched the plug on" marker."""

    def plug_turned_on_at(self) -> datetime | None: ...

    def set_plug_turned_on_at(self, moment: datetime | None) -> None: ...


class PowerPlugController:
    """When to switch the plug on before a wake, and when it is safe to cut it.

    ``policy`` is read at every decision: it returns ``None`` while the plugin is
    disabled or incomplete, so an edit made in Vision applies without a restart.
    """

    def __init__(
        self,
        plug: PowerPlug,
        store: PlugStore,
        *,
        policy: Callable[[], PlugPolicy | None],
    ) -> None:
        self._plug = plug
        self._store = store
        self._policy = policy
        self._lock = threading.Lock()
        self._pending: dict[str, PendingWake] = {}
        self._idle_since: datetime | None = None
        self._last_poll: datetime | None = None
        self._failure_reported_for: datetime | None = None

    @property
    def active(self) -> bool:
        return self._policy() is not None

    def describe(self) -> dict[str, Any] | None:
        """The effective policy, for the administration view (``None`` if off)."""
        policy = self._policy()
        if policy is None:
            return None
        return {
            "boot_delay_seconds": policy.boot_delay_seconds,
            "shutdown_grace_seconds": policy.shutdown_grace_seconds,
            "idle_watts": policy.idle_watts,
            "idle_confirm_seconds": policy.idle_confirm_seconds,
            "poll_seconds": policy.poll_seconds,
        }

    # -- before a wake ---------------------------------------------------

    def begin_wake(self, now: datetime) -> PlugWake:
        """Give the PC power; the Wake-on-LAN follows ``delay_seconds`` later."""
        policy = self._policy()
        if policy is None:
            return PlugWake("disabled")
        try:
            reading = self._plug.read()
        except PowerPlugError as error:
            LOGGER.warning("Power plug unreadable before a wake: %s", error)
            return PlugWake("unreadable", error=str(error))
        if reading.is_on:
            return PlugWake("already_on")
        try:
            self._plug.turn_on()
        except PowerPlugError as error:
            LOGGER.warning("Power plug could not be switched on: %s", error)
            return PlugWake("failed", error=str(error))
        self._store.set_plug_turned_on_at(now)
        self._idle_since = None
        return PlugWake("turned_on", delay_seconds=policy.boot_delay_seconds)

    def hold_wake(
        self, worker_id: str, mac_address: str, trigger: str, now: datetime
    ) -> None:
        """Keep the Wake-on-LAN back until the PC has had power for a moment."""
        policy = self._policy() or PlugPolicy()
        with self._lock:
            self._pending[worker_id] = PendingWake(
                worker_id,
                mac_address,
                trigger,
                now + timedelta(seconds=policy.boot_delay_seconds),
            )

    def due_wakes(self, now: datetime) -> list[PendingWake]:
        """The held Wake-on-LAN packets whose delay has elapsed (removed)."""
        with self._lock:
            due = [wake for wake in self._pending.values() if wake.due_at <= now]
            for wake in due:
                del self._pending[wake.worker_id]
        return due

    def confirm_on(self) -> str | None:
        """Why the plug is not on after the delay, or ``None`` when it is."""
        try:
            return None if self._plug.read().is_on else "the plug is still off"
        except PowerPlugError as error:
            return str(error)

    # -- after a cycle ---------------------------------------------------

    def cut_if_ready(
        self, candidate: PlugCutCandidate | None, now: datetime
    ) -> PlugCut | None:
        """Cut the plug once the PC is demonstrably off; ``None`` means not yet."""
        policy = self._policy()
        if candidate is None or policy is None:
            self._idle_since = None
            return None
        # Only what Ohana switched on, or the plug after a shutdown Ohana ran.
        if (
            candidate.reason != REASON_SHUTDOWN_STARTED
            and self._store.plug_turned_on_at() is None
        ):
            return None
        if (
            self._last_poll is not None
            and (now - self._last_poll).total_seconds() < policy.poll_seconds
        ):
            return None
        self._last_poll = now
        try:
            reading = self._plug.read()
        except PowerPlugError as error:
            return self._failure(candidate, "read", str(error))
        if not reading.is_on:
            self._store.set_plug_turned_on_at(None)
            self._idle_since = None
            return PlugCut("already_off", candidate.reason, {})
        elapsed = int((now - candidate.since).total_seconds())
        if reading.power_watts is not None:
            if reading.power_watts > policy.idle_watts:
                self._idle_since = None
                return None
            if self._idle_since is None:
                self._idle_since = now
            idle_for = int((now - self._idle_since).total_seconds())
            confirm = policy.idle_confirm_seconds
            if idle_for < confirm or elapsed < confirm:
                return None
            evidence: dict[str, Any] = {
                "watts": reading.power_watts,
                "idle_seconds": idle_for,
            }
        elif (
            candidate.reason == REASON_SHUTDOWN_STARTED
            and elapsed >= policy.shutdown_grace_seconds
        ):
            evidence = {"waited_seconds": elapsed}
        else:
            return None
        try:
            self._plug.turn_off()
        except PowerPlugError as error:
            return self._failure(candidate, "off", str(error))
        self._store.set_plug_turned_on_at(None)
        self._idle_since = None
        self._failure_reported_for = None
        return PlugCut(
            "cut", candidate.reason, {**evidence, "after_seconds": max(0, elapsed)}
        )

    def _failure(
        self, candidate: PlugCutCandidate, action: str, error: str
    ) -> PlugCut | None:
        """Retry quietly; report a failing cut once per cycle."""
        if self._failure_reported_for == candidate.since:
            return None
        self._failure_reported_for = candidate.since
        LOGGER.warning("Power plug cut failed (%s): %s", action, error)
        return PlugCut(
            "failed", candidate.reason, {"action": action, "error": error[:200]}
        )
