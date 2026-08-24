"""Persistent Tsunade incident lifecycle built from Shikamaru observations."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field

from administration.models import AdministrationModel
from observer import Observation, ObservationStatus
from observer.events import ObservationPublished

IncidentSeverity = Literal["degraded", "critical"]
IncidentState = Literal["active", "resolved"]
IncidentWorkflowState = Literal["new", "in_progress", "treated", "resolved"]
IncidentExpertiseState = Literal[
    "idle",
    "investigating",
    "deterministic",
    "ai_queued",
    "hypotheses_ready",
    "insufficient_context",
]
IncidentRecordKind = Literal["investigation", "diagnostic", "action", "result"]


class TsunadeIncidentEvent(AdministrationModel):
    """One bounded evolution or operator record attached to an incident."""

    event_id: int
    kind: str = Field(min_length=1, max_length=40)
    occurred_at: datetime
    observation_id: UUID | None = None
    status: str | None = None
    summary: str = Field(min_length=1, max_length=1000)
    payload: dict[str, Any] = Field(default_factory=dict)


class TsunadeIncident(AdministrationModel):
    """One continuous capability degradation owned by Agent/Tsunade."""

    incident_id: UUID
    state: IncidentState
    workflow_state: IncidentWorkflowState
    expertise_state: IncidentExpertiseState
    severity: IncidentSeverity
    node_id: str
    service_id: str
    capability_id: str
    equipment_id: str
    started_at: datetime
    last_observed_at: datetime
    ended_at: datetime | None = None
    last_observation_id: UUID
    message: str
    occurrence_count: int = Field(ge=1)
    recurrence_count: int = Field(ge=0)
    context: dict[str, Any] = Field(default_factory=dict)
    final_result: str | None = None
    events: list[TsunadeIncidentEvent] = Field(default_factory=list)


class TsunadeIncidentRecordRequest(AdministrationModel):
    """A typed note; an action record never executes the action itself."""

    kind: IncidentRecordKind
    summary: str = Field(min_length=1, max_length=1000)
    payload: dict[str, Any] = Field(default_factory=dict)


class TsunadeIncidentRepository:
    """Deduplicate and persist incidents in Agent's existing control database."""

    _FAULTS = {
        ObservationStatus.DEGRADED: "degraded",
        ObservationStatus.UNHEALTHY: "critical",
    }

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def handle(self, event: ObservationPublished) -> None:
        """Consume the existing observation event without creating a new bus."""
        self.process(event.observation)

    def process(self, observation: Observation) -> TsunadeIncident | None:
        """Apply one observation idempotently to its capability incident."""
        key = (observation.node, observation.service, observation.capability)
        with self._lock, self._connection:
            if self._processed(observation.id):
                return None
            previous = self._state(key)
            if previous is not None and observation.timestamp < previous[1]:
                self._mark_processed(observation.id)
                return None
            current = self._active(key)
            severity = self._FAULTS.get(observation.status)
            incident: TsunadeIncident | None = None
            if severity is not None:
                incident = (
                    self._open(
                        observation,
                        severity,
                        previous[0] if previous is not None else "unknown",
                    )
                    if current is None
                    else self._update(current, observation, severity)
                )
            elif (
                observation.status is ObservationStatus.HEALTHY and current is not None
            ):
                incident = self._resolve(current, observation)
            self._write_state(observation)
            self._mark_processed(observation.id)
            return incident

    def list(self, *, state: str = "active", limit: int = 100) -> list[TsunadeIncident]:
        """Return bounded incident history without loading all rows."""
        if state not in {"active", "resolved", "all"}:
            raise ValueError("incident state must be active, resolved, or all")
        if not 1 <= limit <= 500:
            raise ValueError("incident limit must be between 1 and 500")
        condition = {
            "active": "ended_at IS NULL",
            "resolved": "ended_at IS NOT NULL",
            "all": "1 = 1",
        }[state]
        with self._lock:
            rows = self._connection.execute(
                f"""SELECT * FROM tsunade_incidents WHERE {condition}
                ORDER BY (ended_at IS NULL) DESC, started_at DESC LIMIT ?""",  # noqa: S608
                (limit,),
            ).fetchall()
        return [self._incident(row, include_events=False) for row in rows]

    def get(self, incident_id: UUID | str) -> TsunadeIncident:
        """Return one incident with its complete bounded evolution."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM tsunade_incidents WHERE incident_id = ?",
                (str(incident_id),),
            ).fetchone()
        if row is None:
            raise LookupError(f"Unknown incident: {incident_id}")
        return self._incident(row, include_events=True)

    def append_record(
        self,
        incident_id: UUID | str,
        payload: dict[str, Any],
    ) -> TsunadeIncident:
        """Attach investigation, diagnostic, proposed action or final result."""
        request = TsunadeIncidentRecordRequest.model_validate(payload)
        incident = self.get(incident_id)
        now = datetime.now(UTC)
        with self._lock, self._connection:
            self._event(
                incident.incident_id,
                kind=request.kind,
                occurred_at=now,
                summary=request.summary,
                payload=request.payload,
            )
            if request.kind == "result":
                self._connection.execute(
                    """UPDATE tsunade_incidents SET final_result = ?
                    WHERE incident_id = ?""",
                    (request.summary, str(incident.incident_id)),
                )
        return self.get(incident.incident_id)

    def record_log_health(
        self,
        job_id: UUID | str,
        result: dict[str, Any],
        *,
        incident_id: UUID | str | None = None,
    ) -> None:
        """Attach a compact Katsuyu synthesis or maintain its log incident."""
        if incident_id is not None:
            self.append_record(
                incident_id,
                {
                    "kind": "investigation",
                    "summary": (
                        f"Katsuyu log health check: {result.get('status', 'KO')}"
                    ),
                    "payload": result,
                },
            )
            return
        now = datetime.now(UTC)
        with self._lock, self._connection:
            for source in result.get("sources", []):
                if not isinstance(source, dict):
                    continue
                source_id = str(source.get("source", ""))
                if source_id not in {"ha-01", "linky-01", "zwave-01"}:
                    continue
                key = (source_id, "home-assistant", "logs.health")
                current = self._active(key)
                findings = source.get("findings", [])
                if source.get("status") == "OK":
                    if current is not None:
                        self._resolve_log_incident(current, job_id, now, source)
                    continue
                severity = (
                    "critical"
                    if any(
                        isinstance(finding, dict)
                        and finding.get("severity") in {"error", "critical"}
                        for finding in findings
                    )
                    else "degraded"
                )
                message = f"{source_id}: {len(findings)} grouped log anomaly(s)"
                if current is None:
                    recurrence = int(
                        self._connection.execute(
                            """SELECT COUNT(*) FROM tsunade_incidents WHERE
                            node_id=? AND service_id=? AND capability_id=?""",
                            key,
                        ).fetchone()[0]
                    )
                    new_id = uuid4()
                    self._connection.execute(
                        """INSERT INTO tsunade_incidents (
                        incident_id,node_id,service_id,capability_id,equipment_id,
                        severity,started_at,last_observed_at,last_observation_id,
                        message,occurrence_count,recurrence_count,context_json)
                        VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                        (
                            str(new_id),
                            *key,
                            source_id,
                            severity,
                            now.isoformat(),
                            now.isoformat(),
                            str(job_id),
                            message,
                            recurrence,
                            json.dumps(source, ensure_ascii=False, default=str),
                        ),
                    )
                    target_id = new_id
                    kind = "opened"
                else:
                    self._connection.execute(
                        """UPDATE tsunade_incidents SET severity=?,
                        last_observed_at=?,last_observation_id=?,message=?,
                        occurrence_count=occurrence_count+1,context_json=?
                        WHERE incident_id=?""",
                        (
                            severity,
                            now.isoformat(),
                            str(job_id),
                            message,
                            json.dumps(source, ensure_ascii=False, default=str),
                            str(current.incident_id),
                        ),
                    )
                    target_id = current.incident_id
                    kind = "investigation"
                self._event(
                    target_id,
                    kind=kind,
                    occurred_at=now,
                    summary=message,
                    payload={"job_id": str(job_id), "result": source},
                )

    def record_log_investigation(
        self, job_id: UUID | str, incident_id: UUID | str, result: dict[str, Any]
    ) -> None:
        self.append_record(
            incident_id,
            {
                "kind": "investigation",
                "summary": (
                    f"Katsuyu targeted log investigation: "
                    f"{result.get('matched_lines', 0)} matching line(s)"
                ),
                "payload": {"job_id": str(job_id), "result": result},
            },
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _initialize(self) -> None:
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tsunade_incidents (
                incident_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                equipment_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                started_at TEXT NOT NULL,
                last_observed_at TEXT NOT NULL,
                ended_at TEXT,
                last_observation_id TEXT NOT NULL,
                message TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL,
                recurrence_count INTEGER NOT NULL,
                context_json TEXT NOT NULL,
                final_result TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS tsunade_active_capability
            ON tsunade_incidents(node_id, service_id, capability_id)
            WHERE ended_at IS NULL;
            CREATE TABLE IF NOT EXISTS tsunade_incident_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                observation_id TEXT,
                status TEXT,
                summary TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tsunade_events_incident
            ON tsunade_incident_events(incident_id, event_id);
            CREATE TABLE IF NOT EXISTS tsunade_capability_state (
                node_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                status TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                observation_id TEXT NOT NULL,
                PRIMARY KEY(node_id, service_id, capability_id)
            );
            CREATE TABLE IF NOT EXISTS tsunade_processed_observations (
                observation_id TEXT PRIMARY KEY
            );
            """
        )
        self._connection.commit()

    def _open(
        self,
        observation: Observation,
        severity: str,
        previous_status: str,
    ) -> TsunadeIncident:
        incident_id = uuid4()
        key = (observation.node, observation.service, observation.capability)
        recurrence = int(
            self._connection.execute(
                """SELECT COUNT(*) FROM tsunade_incidents
                WHERE node_id = ? AND service_id = ? AND capability_id = ?""",
                key,
            ).fetchone()[0]
        )
        context = self._context(observation.metadata)
        self._connection.execute(
            """INSERT INTO tsunade_incidents (
            incident_id,node_id,service_id,capability_id,equipment_id,severity,
            started_at,last_observed_at,last_observation_id,message,
            occurrence_count,recurrence_count,context_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)""",
            (
                str(incident_id),
                *key,
                str(observation.metadata.get("device_id") or observation.node),
                severity,
                observation.timestamp.isoformat(),
                observation.timestamp.isoformat(),
                str(observation.id),
                observation.message,
                recurrence,
                json.dumps(context, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        self._event(
            incident_id,
            kind="opened",
            occurred_at=observation.timestamp,
            observation=observation,
            summary=observation.message,
            payload={"from": previous_status, "to": severity},
        )
        return self.get(incident_id)

    def _update(
        self,
        incident: TsunadeIncident,
        observation: Observation,
        severity: str,
    ) -> TsunadeIncident:
        kind = (
            "escalated"
            if incident.severity == "degraded" and severity == "critical"
            else "observed"
        )
        self._connection.execute(
            """UPDATE tsunade_incidents SET severity=?,last_observed_at=?,
            last_observation_id=?,message=?,occurrence_count=occurrence_count+1,
            context_json=? WHERE incident_id=?""",
            (
                severity,
                observation.timestamp.isoformat(),
                str(observation.id),
                observation.message,
                json.dumps(self._context(observation.metadata), ensure_ascii=False),
                str(incident.incident_id),
            ),
        )
        self._event(
            incident.incident_id,
            kind=kind,
            occurred_at=observation.timestamp,
            observation=observation,
            summary=observation.message,
            payload={"from": incident.severity, "to": severity},
        )
        return self.get(incident.incident_id)

    def _resolve(
        self, incident: TsunadeIncident, observation: Observation
    ) -> TsunadeIncident:
        result = "Capability returned to healthy state."
        self._connection.execute(
            """UPDATE tsunade_incidents SET ended_at=?,last_observed_at=?,
            last_observation_id=?,message=?,final_result=? WHERE incident_id=?""",
            (
                observation.timestamp.isoformat(),
                observation.timestamp.isoformat(),
                str(observation.id),
                observation.message,
                result,
                str(incident.incident_id),
            ),
        )
        self._event(
            incident.incident_id,
            kind="resolved",
            occurred_at=observation.timestamp,
            observation=observation,
            summary=observation.message,
            payload={"from": incident.severity, "to": "healthy", "result": result},
        )
        return self.get(incident.incident_id)

    def _resolve_log_incident(
        self,
        incident: TsunadeIncident,
        job_id: UUID | str,
        occurred_at: datetime,
        source: dict[str, Any],
    ) -> None:
        result = "Katsuyu found no significant anomaly in the analyzed window."
        self._connection.execute(
            """UPDATE tsunade_incidents SET ended_at=?,last_observed_at=?,
            last_observation_id=?,message=?,final_result=? WHERE incident_id=?""",
            (
                occurred_at.isoformat(),
                occurred_at.isoformat(),
                str(job_id),
                result,
                result,
                str(incident.incident_id),
            ),
        )
        self._event(
            incident.incident_id,
            kind="resolved",
            occurred_at=occurred_at,
            summary=result,
            payload={"job_id": str(job_id), "result": source},
        )

    def _event(
        self,
        incident_id: UUID,
        *,
        kind: str,
        occurred_at: datetime,
        summary: str,
        payload: dict[str, Any],
        observation: Observation | None = None,
    ) -> None:
        self._connection.execute(
            """INSERT INTO tsunade_incident_events
            (incident_id,kind,occurred_at,observation_id,status,summary,payload_json)
            VALUES (?,?,?,?,?,?,?)""",
            (
                str(incident_id),
                kind,
                occurred_at.isoformat(),
                str(observation.id) if observation else None,
                observation.status.value if observation else None,
                summary,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )

    def _active(self, key: tuple[str, str, str]) -> TsunadeIncident | None:
        row = self._connection.execute(
            """SELECT * FROM tsunade_incidents WHERE node_id=? AND service_id=?
            AND capability_id=? AND ended_at IS NULL""",
            key,
        ).fetchone()
        return self._incident(row, include_events=False) if row else None

    def _state(self, key: tuple[str, str, str]) -> tuple[str, datetime] | None:
        row = self._connection.execute(
            """SELECT status,observed_at FROM tsunade_capability_state
            WHERE node_id=? AND service_id=? AND capability_id=?""",
            key,
        ).fetchone()
        return (
            (row["status"], datetime.fromisoformat(row["observed_at"])) if row else None
        )

    def _write_state(self, observation: Observation) -> None:
        self._connection.execute(
            """INSERT INTO tsunade_capability_state VALUES (?,?,?,?,?,?)
            ON CONFLICT(node_id,service_id,capability_id) DO UPDATE SET
            status=excluded.status,observed_at=excluded.observed_at,
            observation_id=excluded.observation_id""",
            (
                observation.node,
                observation.service,
                observation.capability,
                observation.status.value,
                observation.timestamp.isoformat(),
                str(observation.id),
            ),
        )

    def _processed(self, observation_id: UUID) -> bool:
        return (
            self._connection.execute(
                "SELECT 1 FROM tsunade_processed_observations WHERE observation_id=?",
                (str(observation_id),),
            ).fetchone()
            is not None
        )

    def _mark_processed(self, observation_id: UUID) -> None:
        self._connection.execute(
            "INSERT INTO tsunade_processed_observations VALUES (?)",
            (str(observation_id),),
        )

    def _incident(self, row: sqlite3.Row, *, include_events: bool) -> TsunadeIncident:
        events: list[TsunadeIncidentEvent] = []
        handled = False
        if include_events:
            rows = self._connection.execute(
                """SELECT * FROM tsunade_incident_events
                WHERE incident_id=? ORDER BY event_id LIMIT 1000""",
                (row["incident_id"],),
            ).fetchall()
            events = [
                TsunadeIncidentEvent(
                    event_id=int(event["event_id"]),
                    kind=event["kind"],
                    occurred_at=datetime.fromisoformat(event["occurred_at"]),
                    observation_id=event["observation_id"],
                    status=event["status"],
                    summary=event["summary"],
                    payload=json.loads(event["payload_json"]),
                )
                for event in rows
            ]
        if row["ended_at"]:
            workflow_state = "resolved"
        elif row["final_result"]:
            workflow_state = "treated"
        else:
            handled = any(
                event.kind in {"investigation", "diagnostic", "action", "result"}
                for event in events
            )
            if not include_events:
                handled = (
                    self._connection.execute(
                        """SELECT 1 FROM tsunade_incident_events WHERE incident_id=?
                    AND kind IN ('investigation','diagnostic','action','result')
                    LIMIT 1""",
                        (row["incident_id"],),
                    ).fetchone()
                    is not None
                )
            workflow_state = "in_progress" if handled else "new"
        cycle_status: str | None = None
        if include_events:
            cycle_status = next(
                (
                    str(event.payload.get("cycle_status"))
                    for event in reversed(events)
                    if event.kind == "diagnostic" and event.payload.get("cycle_status")
                ),
                None,
            )
        else:
            expertise_row = self._connection.execute(
                """SELECT payload_json FROM tsunade_incident_events
                WHERE incident_id=? AND kind='diagnostic'
                ORDER BY event_id DESC LIMIT 1""",
                (row["incident_id"],),
            ).fetchone()
            if expertise_row is not None:
                cycle_status = str(
                    json.loads(expertise_row["payload_json"]).get("cycle_status") or ""
                )
        expertise_state = {
            "deterministic": "deterministic",
            "ai_queued": "ai_queued",
            "ai_completed": "hypotheses_ready",
            "ai_failed": "insufficient_context",
            "insufficient_context": "insufficient_context",
        }.get(cycle_status or "", "investigating" if handled else "idle")
        return TsunadeIncident(
            incident_id=row["incident_id"],
            state="resolved" if row["ended_at"] else "active",
            workflow_state=workflow_state,
            expertise_state=expertise_state,
            severity=row["severity"],
            node_id=row["node_id"],
            service_id=row["service_id"],
            capability_id=row["capability_id"],
            equipment_id=row["equipment_id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            last_observed_at=datetime.fromisoformat(row["last_observed_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"])
            if row["ended_at"]
            else None,
            last_observation_id=row["last_observation_id"],
            message=row["message"],
            occurrence_count=int(row["occurrence_count"]),
            recurrence_count=int(row["recurrence_count"]),
            context=json.loads(row["context_json"]),
            final_result=row["final_result"],
            events=events,
        )

    @staticmethod
    def _context(metadata: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(metadata, ensure_ascii=False, default=str)
        return (
            json.loads(encoded)
            if len(encoded.encode("utf-8")) <= 32_768
            else {"truncated": True}
        )
