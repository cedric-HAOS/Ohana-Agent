"""Persistent Tsunade incident lifecycle built from Shikamaru observations."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.observation.events import ObservationPublished
from ohana_agent.tsunade.evidence_privacy import (
    redact_sensitive_text,
    redact_sensitive_value,
)
from ohana_agent.tsunade.followup_store import FollowupPersistence
from ohana_agent.tsunade.incident_log_health import TsunadeLogHealthIncidents
from ohana_agent.tsunade.incident_models import (
    TsunadeIncident,
    TsunadeIncidentEvent,
    TsunadeIncidentRecordRequest,
)
from ohana_agent.tsunade.incident_repairs import TsunadeRepairs
from ohana_agent.tsunade.incident_schema import TsunadeIncidentSchema
from ohana_agent.tsunade.incident_user_requests import TsunadeUserRequests


class TsunadeIncidentRepository(
    TsunadeIncidentSchema,
    TsunadeLogHealthIncidents,
    TsunadeRepairs,
    TsunadeUserRequests,
    FollowupPersistence,
):
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
                if current is not None:
                    self._verify_pending_repair(current, observation, succeeded=False)
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
                self._verify_pending_repair(current, observation, succeeded=True)
                incident = self._resolve(current, observation)
            self._write_state(observation)
            self._mark_processed(observation.id)
            return incident

    def reconcile_network_devices(
        self, device_ids: set[str], *, occurred_at: datetime
    ) -> list[TsunadeIncident]:
        """Reconcile persisted presence incidents against current monitoring targets."""
        with self._lock:
            rows = self._connection.execute(
                """SELECT DISTINCT service_id FROM tsunade_incidents
                WHERE capability_id='network.reachable' AND ended_at IS NULL"""
            ).fetchall()
            removed = {row["service_id"] for row in rows} - device_ids
            return self.resolve_removed_network_devices(
                removed, occurred_at=occurred_at
            )

    def resolve_removed_network_devices(
        self, device_ids: set[str], *, occurred_at: datetime
    ) -> list[TsunadeIncident]:
        """Close active presence incidents for devices removed from monitoring.

        This is deliberately not modelled as a healthy observation: the device
        was removed from the declared architecture, so Shikamaru has not
        established that it is reachable.
        """
        if not device_ids:
            return []

        resolved: list[TsunadeIncident] = []
        with self._lock, self._connection:
            rows = self._connection.execute(
                """SELECT * FROM tsunade_incidents
                WHERE capability_id='network.reachable' AND ended_at IS NULL""",
            ).fetchall()
            for row in rows:
                if row["service_id"] not in device_ids:
                    continue
                incident = self._incident(row, include_events=False)
                result = (
                    "La surveillance de cette capacité a été retirée de l’architecture."
                )
                self._connection.execute(
                    """UPDATE tsunade_incidents SET ended_at=?,message=?,final_result=?
                    WHERE incident_id=?""",
                    (
                        occurred_at.isoformat(),
                        result,
                        result,
                        str(incident.incident_id),
                    ),
                )
                self._event(
                    incident.incident_id,
                    kind="monitoring_removed",
                    occurred_at=occurred_at,
                    summary=result,
                    payload={"reason": "architecture_removed"},
                )
                resolved.append(self.get(incident.incident_id))
        return resolved

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
                ORDER BY (ended_at IS NULL) DESC,
                (ended_at IS NULL AND severity='critical') DESC,
                started_at DESC LIMIT ?""",  # noqa: S608
                (limit,),
            ).fetchall()
        return [self._incident(row, include_events=False) for row in rows]

    def statistics(self) -> dict[str, int | float | None]:
        """Return compact history counters without loading incident rows."""
        with self._lock:
            incident_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM tsunade_incidents"
                ).fetchone()[0]
            )
            resolved_incident_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM tsunade_incidents WHERE ended_at IS NOT NULL"
                ).fetchone()[0]
            )
            investigation_count = int(
                self._connection.execute(
                    """SELECT COUNT(*) FROM tsunade_incident_events
                    WHERE kind='investigation'"""
                ).fetchone()[0]
            )
            intervention_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM tsunade_incident_events WHERE kind='action'"
                ).fetchone()[0]
            )
            learned_repair_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM tsunade_experiences"
                ).fetchone()[0]
            )
            repair_rows = self._connection.execute(
                """SELECT status, COUNT(*) AS total FROM tsunade_repairs
                WHERE status IN ('succeeded','failed') GROUP BY status"""
            ).fetchall()
        repair_counts = {str(row["status"]): int(row["total"]) for row in repair_rows}
        succeeded = repair_counts.get("succeeded", 0)
        failed = repair_counts.get("failed", 0)
        verified = succeeded + failed
        return {
            "incident_count": incident_count,
            "resolved_incident_count": resolved_incident_count,
            "investigation_count": investigation_count,
            "intervention_count": intervention_count,
            "learned_repair_count": learned_repair_count,
            "repair_succeeded_count": succeeded,
            "repair_failed_count": failed,
            "repair_success_rate": round((succeeded / verified) * 100, 1)
            if verified
            else None,
        }

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

        summary = redact_sensitive_text(request.summary)
        safe_payload = redact_sensitive_value(request.payload)

        incident = self.get(incident_id)
        now = datetime.now(ZoneInfo("Europe/Paris"))

        with self._lock, self._connection:
            self._event(
                incident.incident_id,
                kind=request.kind,
                occurred_at=now,
                summary=summary,
                payload=safe_payload,
            )

            if request.kind == "result":
                self._connection.execute(
                    """
                    UPDATE tsunade_incidents
                    SET final_result = ?
                    WHERE incident_id = ?
                    """,
                    (
                        summary,
                        str(incident.incident_id),
                    ),
                )

        return self.get(incident.incident_id)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

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
        context = redact_sensitive_value(self._context(observation.metadata))
        message = redact_sensitive_text(observation.message)
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
                message,
                recurrence,
                json.dumps(context, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        self._event(
            incident_id,
            kind="opened",
            occurred_at=observation.timestamp,
            observation=observation,
            summary=message,
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
        message = redact_sensitive_text(observation.message)
        context = redact_sensitive_value(self._context(observation.metadata))
        self._connection.execute(
            """UPDATE tsunade_incidents SET severity=?,last_observed_at=?,
            last_observation_id=?,message=?,occurrence_count=occurrence_count+1,
            context_json=? WHERE incident_id=?""",
            (
                severity,
                observation.timestamp.isoformat(),
                str(observation.id),
                message,
                json.dumps(
                    context,
                    ensure_ascii=False,
                ),
                str(incident.incident_id),
            ),
        )
        self._event(
            incident.incident_id,
            kind=kind,
            occurred_at=observation.timestamp,
            observation=observation,
            summary=message,
            payload={"from": incident.severity, "to": severity},
        )
        return self.get(incident.incident_id)

    def _resolve(
        self, incident: TsunadeIncident, observation: Observation
    ) -> TsunadeIncident:
        result = "La capacité est revenue à un état sain."
        message = redact_sensitive_text(observation.message)
        self._connection.execute(
            """UPDATE tsunade_incidents SET ended_at=?,last_observed_at=?,
            last_observation_id=?,message=?,final_result=? WHERE incident_id=?""",
            (
                observation.timestamp.isoformat(),
                observation.timestamp.isoformat(),
                str(observation.id),
                message,
                result,
                str(incident.incident_id),
            ),
        )
        self._connection.execute(
            """UPDATE tsunade_user_requests SET state='resolved'
            WHERE incident_id=? AND state='pending'""",
            (str(incident.incident_id),),
        )
        self._event(
            incident.incident_id,
            kind="resolved",
            occurred_at=observation.timestamp,
            observation=observation,
            summary=message,
            payload={"from": incident.severity, "to": "healthy", "result": result},
        )
        return self.get(incident.incident_id)

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
        summary = redact_sensitive_text(summary)
        payload = redact_sensitive_value(payload)
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
        repair_rows = self._connection.execute(
            """SELECT * FROM tsunade_repairs WHERE incident_id=?
            ORDER BY proposed_at DESC LIMIT 20""",
            (row["incident_id"],),
        ).fetchall()
        repairs = [self._repair(repair) for repair in repair_rows]
        handled = False
        if include_events:
            rows = self._connection.execute(
                """SELECT * FROM tsunade_incident_events
                WHERE incident_id=? ORDER BY event_id DESC LIMIT 1000""",
                (row["incident_id"],),
            ).fetchall()
            events = [
                TsunadeIncidentEvent(
                    event_id=int(event["event_id"]),
                    kind=event["kind"],
                    occurred_at=datetime.fromisoformat(event["occurred_at"]),
                    observation_id=event["observation_id"],
                    status=event["status"],
                    summary=redact_sensitive_text(str(event["summary"])),
                    payload=redact_sensitive_value(json.loads(event["payload_json"])),
                )
                for event in reversed(rows)
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
            "deterministic_decision": "deterministic",
            "ai_queued": "ai_queued",
            "ai_completed": "hypotheses_ready",
            "ai_failed": "insufficient_context",
            "insufficient_context": "insufficient_context",
        }.get(cycle_status or "", "investigating" if handled else "idle")
        decision_row = self._connection.execute(
            """SELECT payload_json, occurred_at FROM tsunade_incident_events
            WHERE incident_id=? AND kind='diagnostic'
            ORDER BY event_id DESC LIMIT 1""",
            (row["incident_id"],),
        ).fetchone()
        decision_payload = (
            redact_sensitive_value(json.loads(decision_row["payload_json"]))
            if decision_row
            else {}
        )
        latest_decision = (
            {
                **{
                    key: value
                    for key, value in decision_payload.items()
                    if key
                    in {
                        "decision",
                        "decision_source",
                        "origin",
                        "epistemic_status",
                        "diagnostic_level",
                        "confirmation_gap",
                        "interpretation",
                        "summary",
                        "confidence",
                        "conclusion",
                        "reason",
                        "recommended_action",
                        "reevaluate_after",
                        "cycle_status",
                        "basis_observed_at",
                        "basis_fingerprint",
                        "verdict",
                        "ai_job_id",
                        "upstream_incident_id",
                    }
                },
                "occurred_at": decision_row["occurred_at"],
            }
            if decision_row
            else None
        )
        incident = TsunadeIncident(
            incident_id=row["incident_id"],
            followup=self.latest_followup(row["incident_id"]),
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
            message=redact_sensitive_text(str(row["message"])),
            occurrence_count=int(row["occurrence_count"]),
            recurrence_count=int(row["recurrence_count"]),
            context=redact_sensitive_value(json.loads(row["context_json"])),
            latest_decision=latest_decision,
            final_result=(
                redact_sensitive_text(str(row["final_result"]))
                if row["final_result"]
                else None
            ),
            events=events,
            repairs=repairs,
        )
        if include_events:
            incident.experience_candidate = self._experience_candidate(incident)
        return incident

    @staticmethod
    def _bounded_anomalies(context: dict[str, Any]) -> list[dict[str, Any]]:
        findings = context.get("findings", []) if isinstance(context, dict) else []
        return [finding for finding in findings[:16] if isinstance(finding, dict)]

    @staticmethod
    def _context(metadata: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(metadata, ensure_ascii=False, default=str)
        return (
            json.loads(encoded)
            if len(encoded.encode("utf-8")) <= 32_768
            else {"truncated": True}
        )
