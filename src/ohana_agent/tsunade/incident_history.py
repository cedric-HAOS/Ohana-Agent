"""Phase 3 hardening: incident history for Vision, and similar incidents.

Search of past incidents by equipment, capability, period and outcome; one
sheet per equipment; a 30-day timeline of incidents and repairs; for one
incident, the past incidents most alike and what resolved them. Read only.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from threading import RLock
from typing import Any
from uuid import UUID

from ohana_agent.tsunade.incident_similarity import (
    SIMILAR_THRESHOLD,
    compare,
    fingerprint,
)
from ohana_agent.tsunade.local_time import paris_iso, paris_now, to_paris

OUTCOMES = ("ongoing", "repaired", "manual", "resolved")
MAX_HISTORY = 500
SIMILAR_CANDIDATES = 300

# Resolved by a verified repair, by a confirmed manual action, or on its own.
# The message at opening: a resolved incident keeps its recovery message.
_OPENED_SQL = """(SELECT e.summary FROM tsunade_incident_events e
    WHERE e.incident_id = i.incident_id AND e.kind = 'opened' LIMIT 1)"""

_OUTCOME_SQL = """CASE
    WHEN i.ended_at IS NULL THEN 'ongoing'
    WHEN EXISTS (SELECT 1 FROM tsunade_repairs r
        WHERE r.incident_id = i.incident_id AND r.status = 'succeeded')
        THEN 'repaired'
    WHEN EXISTS (SELECT 1 FROM tsunade_manual_actions m
        WHERE m.incident_id = i.incident_id AND m.status = 'confirmed')
        THEN 'manual'
    ELSE 'resolved' END"""


class TsunadeIncidentHistory:
    _connection: sqlite3.Connection
    _lock: RLock

    def history(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Past and open incidents matching optional filters, newest first."""
        filters = payload or {}
        conditions: list[str] = []
        values: list[Any] = []
        for column in ("equipment_id", "capability_id"):
            value = filters.get(column)
            if value:
                conditions.append(f"i.{column} = ?")
                values.append(str(value))
        for key, operator in (("since", ">="), ("until", "<=")):
            value = filters.get(key)
            if value:
                moment = to_paris(datetime.fromisoformat(str(value)))
                conditions.append(f"julianday(i.started_at) {operator} julianday(?)")
                values.append(paris_iso(moment))
        outcome = filters.get("outcome")
        if outcome:
            if outcome not in OUTCOMES:
                raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}")
            conditions.append(f"({_OUTCOME_SQL}) = ?")
            values.append(outcome)
        limit = filters.get("limit", 200)
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        limit = max(1, min(limit, MAX_HISTORY))
        where = " AND ".join(conditions) or "1 = 1"
        with self._lock:
            rows = self._connection.execute(
                f"""SELECT i.incident_id, i.node_id, i.service_id, i.capability_id,
                i.equipment_id, i.severity, i.started_at, i.ended_at, i.message,
                i.final_result, i.recurrence_count, ({_OUTCOME_SQL}) AS outcome,
                {_OPENED_SQL} AS opened_summary,
                EXISTS (SELECT 1 FROM tsunade_repairs r
                    WHERE r.incident_id = i.incident_id AND r.status = 'failed')
                    AS repair_failed
                FROM tsunade_incidents i WHERE {where}
                ORDER BY julianday(i.started_at) DESC LIMIT ?""",  # noqa: S608
                (*values, limit),
            ).fetchall()
            facets = self._history_facets()
        return {
            "schema_version": 1,
            "generated_at": paris_iso(paris_now()),
            "incidents": [_history_item(row) for row in rows],
            "facets": facets,
            "limit": limit,
        }

    def equipment_history(self, equipment_id: str) -> dict[str, Any]:
        """One equipment's incidents, repairs and known repairs."""
        with self._lock:
            by_capability = self._connection.execute(
                """SELECT capability_id, COUNT(*) AS total,
                MAX(started_at) AS last_started_at,
                SUM(ended_at IS NULL) AS open_count
                FROM tsunade_incidents WHERE equipment_id = ?
                GROUP BY capability_id ORDER BY total DESC""",
                (equipment_id,),
            ).fetchall()
            if not by_capability:
                raise LookupError(f"Aucun incident connu pour {equipment_id}")
            durations = self._connection.execute(
                """SELECT SUM((julianday(ended_at) - julianday(started_at)) * 86400)
                FROM tsunade_incidents
                WHERE equipment_id = ? AND ended_at IS NOT NULL""",
                (equipment_id,),
            ).fetchone()[0]
            repairs = self._connection.execute(
                """SELECT r.status, COUNT(*) FROM tsunade_repairs r
                JOIN tsunade_incidents i ON i.incident_id = r.incident_id
                WHERE i.equipment_id = ? AND r.executed_at IS NOT NULL
                GROUP BY r.status""",
                (equipment_id,),
            ).fetchall()
            manual = self._connection.execute(
                """SELECT m.status, COUNT(*) FROM tsunade_manual_actions m
                JOIN tsunade_incidents i ON i.incident_id = m.incident_id
                WHERE i.equipment_id = ? GROUP BY m.status""",
                (equipment_id,),
            ).fetchall()
            experiences = self._connection.execute(
                """SELECT experience_id, capability_id, validated_diagnostic,
                action_json, state, success_count, failure_count, last_success_at
                FROM tsunade_experiences WHERE equipment_id = ?
                ORDER BY state <> 'active', julianday(last_used_at) DESC""",
                (equipment_id,),
            ).fetchall()
        repair_counts = {str(row[0]): int(row[1]) for row in repairs}
        succeeded = repair_counts.get("succeeded", 0)
        failed = repair_counts.get("failed", 0)
        manual_counts = {str(row[0]): int(row[1]) for row in manual}
        recent = self.history({"equipment_id": equipment_id, "limit": 10})
        return {
            "schema_version": 1,
            "equipment_id": equipment_id,
            "incident_count": sum(int(row["total"]) for row in by_capability),
            "open_count": sum(int(row["open_count"] or 0) for row in by_capability),
            "total_duration_seconds": round(durations or 0),
            "by_capability": [
                {
                    "capability_id": row["capability_id"],
                    "count": int(row["total"]),
                    "open_count": int(row["open_count"] or 0),
                    "last_started_at": paris_iso(row["last_started_at"]),
                }
                for row in by_capability
            ],
            "repairs": {
                "executed": sum(repair_counts.values()),
                "succeeded": succeeded,
                "failed": failed,
                "success_rate": (
                    round(succeeded / (succeeded + failed) * 100, 1)
                    if succeeded + failed
                    else None
                ),
            },
            "manual_actions": {
                "declared": sum(manual_counts.values()),
                "confirmed": manual_counts.get("confirmed", 0),
            },
            "known_repairs": [
                {
                    "experience_id": row["experience_id"],
                    "capability_id": row["capability_id"],
                    "diagnostic": row["validated_diagnostic"],
                    "action": json.loads(row["action_json"]),
                    "state": row["state"],
                    "success_count": int(row["success_count"]),
                    "failure_count": int(row["failure_count"]),
                    "last_success_at": (
                        paris_iso(row["last_success_at"])
                        if row["last_success_at"]
                        else None
                    ),
                }
                for row in experiences
            ],
            "recent": recent["incidents"],
        }

    def timeline(self, *, days: int = 30) -> dict[str, Any]:
        """Incidents and executed repairs of the last ``days`` days."""
        if not 1 <= days <= 90:
            raise ValueError("days must be between 1 and 90")
        until = paris_now()
        since = until - timedelta(days=days)
        incidents = self.history({"since": since.isoformat(), "limit": MAX_HISTORY})
        with self._lock:
            repairs = self._connection.execute(
                """SELECT r.incident_id, r.operation, r.target, r.status,
                r.executed_at, i.equipment_id
                FROM tsunade_repairs r
                JOIN tsunade_incidents i ON i.incident_id = r.incident_id
                WHERE r.executed_at IS NOT NULL
                AND julianday(r.executed_at) >= julianday(?)
                ORDER BY julianday(r.executed_at)""",
                (paris_iso(since),),
            ).fetchall()
        return {
            "schema_version": 1,
            "since": paris_iso(since),
            "until": paris_iso(until),
            "incidents": incidents["incidents"],
            "repairs": [
                {
                    "incident_id": row["incident_id"],
                    "equipment_id": row["equipment_id"],
                    "operation": row["operation"],
                    "target": row["target"],
                    "status": row["status"],
                    "executed_at": paris_iso(row["executed_at"]),
                }
                for row in repairs
            ],
        }

    def similar_incidents(
        self, incident_id: UUID | str, *, limit: int = 5
    ) -> dict[str, Any]:
        """Past incidents most alike, with what matched and what resolved them."""
        with self._lock:
            row = self._connection.execute(
                f"""SELECT i.*, {_OPENED_SQL} AS opened_summary
                FROM tsunade_incidents i WHERE i.incident_id = ?""",  # noqa: S608
                (str(incident_id),),
            ).fetchone()
            if row is None:
                raise LookupError("Incident introuvable")
            candidates = self._connection.execute(
                f"""SELECT i.*, ({_OUTCOME_SQL}) AS outcome,
                {_OPENED_SQL} AS opened_summary,
                EXISTS (SELECT 1 FROM tsunade_repairs r
                    WHERE r.incident_id = i.incident_id AND r.status = 'failed')
                    AS repair_failed
                FROM tsunade_incidents i
                WHERE i.capability_id = ? AND i.incident_id <> ?
                AND i.ended_at IS NOT NULL
                ORDER BY julianday(i.started_at) DESC LIMIT ?""",  # noqa: S608
                (row["capability_id"], row["incident_id"], SIMILAR_CANDIDATES),
            ).fetchall()
        reference = _fingerprint(row)
        found = []
        for candidate in candidates:
            comparison = compare(reference, _fingerprint(candidate))
            if comparison["score"] < SIMILAR_THRESHOLD:
                continue
            found.append({**_history_item(candidate), "similarity": comparison})
        found.sort(key=lambda item: item["similarity"]["score"], reverse=True)
        return {
            "schema_version": 1,
            "incident_id": row["incident_id"],
            "threshold": SIMILAR_THRESHOLD,
            "similar": found[:limit],
            "note": (
                "Ressemblance sur les symptômes et les preuves ; la proximité dans "
                "le temps n'est pas un critère et une ressemblance n'est pas une cause."
            ),
        }

    def _history_facets(self) -> dict[str, list[str]]:
        return {
            column: [
                str(value[0])
                for value in self._connection.execute(
                    f"SELECT DISTINCT {column} FROM tsunade_incidents "  # noqa: S608
                    f"ORDER BY {column}"
                )
            ]
            for column in ("equipment_id", "capability_id")
        }


def _fingerprint(row: sqlite3.Row) -> dict[str, Any]:
    try:
        context = json.loads(row["context_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        context = {}
    return fingerprint(
        equipment_id=row["equipment_id"],
        capability_id=row["capability_id"],
        service_id=row["service_id"],
        message=row["opened_summary"] or row["message"],
        context=context,
    )


def _history_item(row: sqlite3.Row) -> dict[str, Any]:
    started = to_paris(datetime.fromisoformat(row["started_at"]))
    ended = (
        to_paris(datetime.fromisoformat(row["ended_at"])) if row["ended_at"] else None
    )
    return {
        "incident_id": row["incident_id"],
        "equipment_id": row["equipment_id"],
        "node_id": row["node_id"],
        "service_id": row["service_id"],
        "capability_id": row["capability_id"],
        "severity": row["severity"],
        "started_at": paris_iso(started),
        "ended_at": paris_iso(ended) if ended else None,
        "duration_seconds": int((ended - started).total_seconds()) if ended else None,
        "message": row["message"],
        # What went wrong: a resolved incident's message is its recovery.
        "opening_message": row["opened_summary"],
        "final_result": row["final_result"],
        "recurrence_count": int(row["recurrence_count"] or 0),
        "outcome": row["outcome"],
        "repair_failed": bool(row["repair_failed"]),
    }
