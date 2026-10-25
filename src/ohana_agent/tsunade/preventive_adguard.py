"""Preventive rule: AdGuard Home protection paused for too long.

AdGuard can pause its filtering for a while (or without end). A short pause is
routine; one that lasts hours is easy to forget and leaves the whole network
unfiltered. The Agent already reads the origin's DNS settings every minute: this
module keeps how long the pause has lasted and reports it. It never changes
AdGuard.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from ohana_agent.tsunade.local_time import paris_iso, to_paris

RULE: dict[str, str] = {
    "id": "adguard_protection",
    "title": "Protection AdGuard suspendue",
    "rule": (
        "La protection d'AdGuard Home est suspendue depuis plus de 2 heures "
        "(pause temporaire ou sans fin prévue). Une pause courte est normale ; "
        "elle n'est signalée qu'au-delà. L'Agent ne la lève jamais."
    ),
}
PAUSE_WATCH_AFTER = timedelta(hours=2)
# The reading comes with the replication check, about every minute: a pause not
# seen for this long is no longer evidence of anything.
STALE_AFTER = timedelta(minutes=30)
PERSIST_EVERY = timedelta(minutes=15)
SCHEMA = """
CREATE TABLE IF NOT EXISTS tsunade_adguard_pause (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    since TEXT NOT NULL,
    until TEXT,
    last_seen TEXT NOT NULL
);
"""


class AdGuardPauseTracker:
    """Remember since when the protection has been paused."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        connection.executescript(SCHEMA)
        row = connection.execute("SELECT * FROM tsunade_adguard_pause").fetchone()
        self._since: datetime | None = None
        self._until: str | None = None
        self._last_seen: datetime | None = None
        self._persisted_at: datetime | None = None
        self._read_at: datetime | None = None
        if row is not None:
            self._since = _parse(row["since"])
            self._until = row["until"]
            self._last_seen = _parse(row["last_seen"])
            self._persisted_at = self._last_seen

    def observe(self, enabled: bool | None, until: str | None, at: datetime) -> None:
        """Record one reading of the origin's ``protection_*`` settings."""
        at = to_paris(at)
        if enabled is None:
            return
        self._read_at = at
        if enabled:
            if self._since is not None:
                self._since = self._until = self._last_seen = None
                self._connection.execute("DELETE FROM tsunade_adguard_pause")
                self._connection.commit()
            return
        # A pause seen again after a long gap is a new pause.
        if (
            self._since is None
            or self._last_seen is None
            or at - self._last_seen > STALE_AFTER
        ):
            self._since = at
            self._persisted_at = None
        changed = until != self._until
        self._until = until
        self._last_seen = at
        if (
            self._persisted_at is None
            or changed
            or (at - self._persisted_at >= PERSIST_EVERY)
        ):
            self._connection.execute(
                """INSERT INTO tsunade_adguard_pause (id, since, until, last_seen)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET since = excluded.since,
                    until = excluded.until, last_seen = excluded.last_seen""",
                (paris_iso(self._since), until, paris_iso(at)),
            )
            self._connection.commit()
            self._persisted_at = at

    def check(self, current: datetime) -> dict[str, Any]:
        current = to_paris(current)
        paused = (
            self._since is not None
            and self._last_seen is not None
            and current - self._last_seen <= STALE_AFTER
        )
        if not paused:
            return {
                **RULE,
                "state": "ok" if self._read_at is not None else "insufficient_data",
                "nodes": [
                    {
                        "node_id": "adguard",
                        "state": "ok",
                        "summary": "AdGuard : protection active",
                    }
                ],
                "items": [],
            }
        assert self._since is not None
        duration = current - self._since
        long = duration >= PAUSE_WATCH_AFTER
        ends = f"jusqu'au {_short(self._until)}" if self._until else "sans fin prévue"
        summary = f"AdGuard : protection suspendue depuis {_hours(duration)}, {ends}"
        items = []
        if long:
            items.append(
                {
                    "rule": RULE["id"],
                    "node_id": "infra-01",
                    "equipment_id": "infra-01",
                    "subject": "adguard-protection",
                    "title": (
                        f"AdGuard : protection suspendue depuis {_hours(duration)}"
                    ),
                    "detail": (
                        f"Le filtrage DNS est suspendu depuis le "
                        f"{_short(paris_iso(self._since))}, {ends}. Tant qu'elle "
                        "dure, aucun appareil du réseau n'est filtré."
                    ),
                    "since": paris_iso(self._since),
                    "urgent": False,
                    "evidence": {
                        "paused_since": paris_iso(self._since),
                        "paused_until": self._until,
                    },
                }
            )
        return {
            **RULE,
            "state": "watch" if items else "ok",
            "nodes": [
                {
                    "node_id": "adguard",
                    "state": "watch" if items else "ok",
                    "summary": summary,
                }
            ],
            "items": items,
        }


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _hours(duration: timedelta) -> str:
    minutes = int(duration.total_seconds() // 60)
    if minutes < 120:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


def _short(value: str | None) -> str:
    if not value:
        return ""
    moment = to_paris(datetime.fromisoformat(value))
    return moment.strftime("%d/%m à %H:%M")
