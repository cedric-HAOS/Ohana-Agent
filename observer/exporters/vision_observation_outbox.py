"""Durable SQLite outbox for observations awaiting Ohana-Vision."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass(frozen=True, slots=True)
class VisionObservationOutboxEntry:
    """One observation waiting to be delivered."""

    observation_id: str
    payload: dict[str, Any]
    attempts: int


class VisionObservationOutbox:
    """Persist observations until Vision acknowledges their delivery."""

    _SCHEMA_VERSION = 1

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._closed = False
        self._initialize_database()

    @property
    def pending_count(self) -> int:
        """Return the number of observations awaiting delivery."""
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS count FROM observation_outbox"
            ).fetchone()
            return int(row["count"])

    def enqueue(self, payload: dict[str, Any]) -> None:
        """Persist a payload once, identified by its observation UUID."""
        observation_id = str(payload.get("observation_id", "")).strip()
        if not observation_id:
            raise ValueError("Vision observation payload must contain observation_id.")

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO observation_outbox (
                    observation_id, payload_json, enqueued_at
                ) VALUES (?, ?, ?)
                """,
                (observation_id, serialized, datetime.now(UTC).isoformat()),
            )
            self._connection.commit()

    def oldest(self) -> VisionObservationOutboxEntry | None:
        """Return the oldest pending payload."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT observation_id, payload_json, attempts
                FROM observation_outbox
                ORDER BY sequence
                LIMIT 1
                """
            ).fetchone()

        if row is None:
            return None

        return VisionObservationOutboxEntry(
            observation_id=row["observation_id"],
            payload=json.loads(row["payload_json"]),
            attempts=int(row["attempts"]),
        )

    def mark_delivered(self, observation_id: str) -> None:
        """Remove one successfully delivered observation."""
        with self._lock:
            self._connection.execute(
                "DELETE FROM observation_outbox WHERE observation_id = ?",
                (observation_id,),
            )
            self._connection.commit()

    def mark_failed(self, observation_id: str, error: str) -> None:
        """Record one failed delivery attempt without dropping its payload."""
        with self._lock:
            self._connection.execute(
                """
                UPDATE observation_outbox
                SET attempts = attempts + 1,
                    last_error = ?,
                    last_attempt_at = ?
                WHERE observation_id = ?
                """,
                (error, datetime.now(UTC).isoformat(), observation_id),
            )
            self._connection.commit()

    def close(self) -> None:
        """Close the SQLite database."""
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def _initialize_database(self) -> None:
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if version > self._SCHEMA_VERSION:
            self._connection.close()
            raise RuntimeError("Vision outbox schema is newer than this Agent version.")

        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS observation_outbox (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_id TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                enqueued_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                last_attempt_at TEXT
            )
            """
        )
        self._connection.execute(f"PRAGMA user_version={self._SCHEMA_VERSION}")
        self._connection.commit()
