"""Incidents opened and resolved from Katsuyu log health reviews."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from ohana_agent.tsunade.evidence_privacy import (
    redact_sensitive_value,
)
from ohana_agent.tsunade.incident_models import (
    TsunadeIncident,
)
from ohana_agent.tsunade.local_time import paris_now


def log_check_summary(result: dict[str, Any]) -> str:
    """Describe what Katsuyu found; its "KO" means anomalies, not a failed job."""
    sources = [
        source for source in result.get("sources", []) if isinstance(source, dict)
    ]
    findings = sum(
        len(source.get("findings") or [])
        for source in sources
        if isinstance(source.get("findings") or [], list)
    )
    incomplete = any(source.get("truncated") is True for source in sources)
    if findings:
        outcome = f"{findings} anomalie(s) regroupée(s)"
    elif result.get("status") == "OK":
        outcome = "aucune anomalie"
    else:
        outcome = "résultat sans synthèse exploitable"
    if incomplete:
        outcome += ", collecte incomplète"
    return f"Contrôle des journaux par Katsuyu terminé : {outcome}"


class TsunadeLogHealthIncidents:
    """Incidents opened and resolved from Katsuyu log health reviews."""

    def record_log_health(
        self,
        job_id: UUID | str,
        result: dict[str, Any],
        *,
        incident_id: UUID | str | None = None,
    ) -> list[UUID]:
        """Attach a compact Katsuyu synthesis or maintain its log incident."""
        result = redact_sensitive_value(result)
        if incident_id is not None:
            incident = self.get(incident_id)
            if any(
                event.payload.get("job_id") == str(job_id) for event in incident.events
            ):
                return [incident.incident_id]
            self.append_record(
                incident_id,
                {
                    "kind": "investigation",
                    "summary": log_check_summary(result),
                    "payload": {**result, "job_id": str(job_id)},
                },
            )
            return [incident.incident_id]
        now = paris_now()
        affected: list[UUID] = []
        with self._lock, self._connection:
            for source in result.get("sources", []):
                if not isinstance(source, dict):
                    continue
                source = {
                    **source,
                    "analyzed_at": result.get("analyzed_at"),
                    "window_started_at": result.get("window_started_at"),
                    "window_ended_at": result.get("window_ended_at"),
                }
                source_id = str(source.get("source", ""))
                if source_id not in {
                    "infra-01",
                    "ha-01",
                    "linky-01",
                    "zwave-01",
                }:
                    continue
                service_id = (
                    "system-journal" if source_id == "infra-01" else "home-assistant"
                )
                key = (source_id, service_id, "logs.health")
                current = self._active(key)
                if current is None and source_id == "infra-01":
                    legacy = self._active((source_id, "home-assistant", "logs.health"))
                    if legacy is not None:
                        self._connection.execute(
                            "UPDATE tsunade_incidents SET service_id=? "
                            "WHERE incident_id=?",
                            (service_id, str(legacy.incident_id)),
                        )
                        current = self._active(key)
                recorded = self._connection.execute(
                    """SELECT i.incident_id, i.ended_at FROM tsunade_incident_events e
                    JOIN tsunade_incidents i ON i.incident_id=e.incident_id
                    WHERE i.equipment_id=? AND i.capability_id='logs.health'
                    AND json_extract(e.payload_json, '$.job_id')=? LIMIT 1""",
                    (source_id, str(job_id)),
                ).fetchone()
                if recorded is not None:
                    if recorded["ended_at"] is None:
                        affected.append(UUID(recorded["incident_id"]))
                    continue
                if current is not None and str(current.last_observation_id) == str(
                    job_id
                ):
                    affected.append(current.incident_id)
                    continue
                findings = source.get("findings", [])
                if source.get("status") == "OK":
                    if source.get("truncated") is False:
                        if current is not None:
                            self._resolve_log_incident(current, job_id, now, source)
                        continue
                    if current is None:
                        # Missing coverage does not establish a new service fault.
                        continue
                    source["historical_findings"] = current.context.get(
                        "findings"
                    ) or current.context.get("historical_findings", [])
                severity = "degraded"
                message = (
                    f"{source_id} : collecte incomplète ; résolution non vérifiée"
                    if source.get("status") == "OK"
                    else f"{source_id} : {len(findings)} anomalie(s) "
                    "de journaux regroupée(s)"
                )
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
                affected.append(target_id)
        return affected

    def record_log_investigation(
        self, job_id: UUID | str, incident_id: UUID | str, result: dict[str, Any]
    ) -> None:
        if any(
            event.payload.get("job_id") == str(job_id) and "result" in event.payload
            for event in self.get(incident_id).events
        ):
            return
        self.append_record(
            incident_id,
            {
                "kind": "investigation",
                "summary": (
                    f"Investigation ciblée des journaux par Katsuyu : "
                    f"{result.get('matched_lines', 0)} ligne(s) correspondante(s)"
                ),
                "payload": {"job_id": str(job_id), "result": result},
            },
        )

    def reviewed_log_findings(self, incident_id: UUID | str) -> set[str]:
        """Read durable evidence markers beyond the bounded display history."""
        with self._lock:
            rows = self._connection.execute(
                """SELECT DISTINCT marker.value FROM tsunade_incident_events event,
                json_each(event.payload_json, '$.reviewed_log_findings') marker
                WHERE event.incident_id=? AND marker.type='text'""",
                (str(incident_id),),
            ).fetchall()
        return {row[0] for row in rows}

    def _resolve_log_incident(
        self,
        incident: TsunadeIncident,
        job_id: UUID | str,
        occurred_at: datetime,
        source: dict[str, Any],
    ) -> None:
        result = (
            "Katsuyu n’a trouvé aucune anomalie significative dans la période analysée."
        )
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
        self._connection.execute(
            """UPDATE tsunade_user_requests SET state='resolved'
            WHERE incident_id=? AND state='pending'""",
            (str(incident.incident_id),),
        )
        self._event(
            incident.incident_id,
            kind="resolved",
            occurred_at=occurred_at,
            summary=result,
            payload={"job_id": str(job_id), "result": source},
        )
