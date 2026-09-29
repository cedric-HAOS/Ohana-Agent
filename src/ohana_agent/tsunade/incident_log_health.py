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
from ohana_agent.tsunade.log_components import (
    annotate_log_finding,
    canonical_component,
    component_label,
    component_overview,
)


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


# A warning repeated this often in 24 h is a symptom, not noise: the DNS
# fault on LINKY-01 (2 764 refusals a day) only ever logged warnings.
LOG_WARNING_VOLUME = 100


def is_significant_log_finding(finding: dict[str, Any]) -> bool:
    """Errors and high-volume warnings justify an incident; the rest is reported."""
    if finding.get("severity") in {"error", "critical"}:
        return True
    try:
        return int(finding.get("occurrences") or 0) >= LOG_WARNING_VOLUME
    except (TypeError, ValueError):
        return False


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
                findings = source.get("findings") or []
                split = self._split_log_findings(source_id, findings)
                source = {**source, **split}
                significant = split["findings"]
                collection_failed = source.get("status") != "OK" and not findings
                if not significant and not collection_failed:
                    if current is not None:
                        self._resolve_log_incident(current, job_id, now, source)
                    continue
                severity = "degraded"
                message = (
                    f"{source_id} : collecte des journaux sans résultat exploitable"
                    if collection_failed
                    else f"{source_id} : {len(significant)} anomalie(s) "
                    "significative(s) dans les journaux"
                )
                if source.get("truncated") is True:
                    message += " (collecte incomplète)"
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

    def _split_log_findings(
        self, source_id: str, findings: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Separate what justifies an incident from routine and accepted noise."""
        accepted = {
            row[0]
            for row in self._connection.execute(
                "SELECT signature FROM tsunade_accepted_log_signatures WHERE source=?",
                (source_id,),
            )
        }
        accepted_components = self._accepted_components().get(source_id, set())
        split: dict[str, list[dict[str, Any]]] = {
            "findings": [],
            "background_findings": [],
            "accepted_findings": [],
        }
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            finding = annotate_log_finding(finding)
            if finding.get("signature") in accepted or (
                # Accepting a component never hides a critical line.
                finding["component"] in accepted_components
                and finding.get("severity") != "critical"
            ):
                split["accepted_findings"].append(finding)
            elif is_significant_log_finding(finding):
                split["findings"].append(finding)
            else:
                split["background_findings"].append(finding)
        return split

    def _accepted_components(self) -> dict[str, set[str]]:
        accepted: dict[str, set[str]] = {}
        for source, component in self._connection.execute(
            "SELECT source, component FROM tsunade_accepted_log_components"
        ):
            # Ids accepted before two names were merged (aioshelly, shelly).
            accepted.setdefault(source, set()).add(canonical_component(component))
        return accepted

    def accepted_log_components(self) -> list[dict[str, str]]:
        """Return the components the user accepted as known noise."""
        with self._lock:
            rows = self._connection.execute(
                """SELECT source, component, label, accepted_at
                FROM tsunade_accepted_log_components ORDER BY source, label"""
            ).fetchall()
        merged: dict[tuple[str, str], dict[str, str]] = {}
        for source, component, label, accepted_at in rows:
            canonical = canonical_component(component)
            merged.setdefault(
                (source, canonical),
                {
                    "source": source,
                    "component": canonical,
                    "label": component_label(canonical, label),
                    "accepted_at": accepted_at,
                },
            )
        return sorted(merged.values(), key=lambda item: (item["source"], item["label"]))

    def log_component_overview(self, result: Any) -> list[dict[str, Any]]:
        """Read the last review by component, with what the user accepted."""
        if not isinstance(result, dict):
            return []
        with self._lock:
            accepted = self._accepted_components()
        return component_overview(result.get("sources") or [], accepted)

    def accept_log_component(self, source: str, component: str, label: str) -> None:
        """Stop counting the non-critical anomalies of one component."""
        now = paris_now()
        component = canonical_component(component)
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT OR REPLACE INTO tsunade_accepted_log_components
                (source, component, label, accepted_at) VALUES (?,?,?,?)""",
                (
                    source,
                    component,
                    component_label(component, label)[:120],
                    now.isoformat(),
                ),
            )
            current = self._active(
                (
                    source,
                    "system-journal" if source == "infra-01" else "home-assistant",
                    "logs.health",
                )
            )
            if current is None:
                return
            known = [
                *current.context.get("findings", []),
                *current.context.get("background_findings", []),
                *current.context.get("accepted_findings", []),
            ]
            context = {**current.context, **self._split_log_findings(source, known)}
            if not context["findings"]:
                self._resolve_log_incident(
                    current, current.last_observation_id, now, context
                )
                return
            self._connection.execute(
                "UPDATE tsunade_incidents SET context_json=?,message=? "
                "WHERE incident_id=?",
                (
                    json.dumps(context, ensure_ascii=False, default=str),
                    f"{source} : {len(context['findings'])} anomalie(s) "
                    "significative(s) dans les journaux",
                    str(current.incident_id),
                ),
            )
            self._event(
                current.incident_id,
                kind="investigation",
                occurred_at=now,
                summary=f"Composant accepté comme connu : {label[:120]}",
                payload={"accepted_component": component},
            )

    def revoke_log_component(self, source: str, component: str) -> bool:
        """Count one accepted component again from the next review."""
        canonical = canonical_component(component)
        with self._lock, self._connection:
            stored = [
                row[0]
                for row in self._connection.execute(
                    "SELECT component FROM tsunade_accepted_log_components "
                    "WHERE source=?",
                    (source,),
                )
                if canonical_component(row[0]) == canonical
            ]
            for name in stored:
                self._connection.execute(
                    "DELETE FROM tsunade_accepted_log_components "
                    "WHERE source=? AND component=?",
                    (source, name),
                )
        return bool(stored)

    def accepted_log_signatures(self) -> list[dict[str, str]]:
        """Return the signatures the user accepted as known noise."""
        with self._lock:
            rows = self._connection.execute(
                """SELECT source, signature, summary, accepted_at
                FROM tsunade_accepted_log_signatures ORDER BY source, accepted_at"""
            ).fetchall()
        return [
            {
                "source": row[0],
                "signature": row[1],
                "summary": row[2],
                "accepted_at": row[3],
            }
            for row in rows
        ]

    def accept_log_signature(self, source: str, signature: str) -> None:
        """Stop counting one anomaly signature; resolve what it alone kept open."""
        now = paris_now()
        with self._lock, self._connection:
            key = (
                source,
                "system-journal" if source == "infra-01" else "home-assistant",
                "logs.health",
            )
            current = self._active(key)
            known = (
                [
                    *current.context.get("findings", []),
                    *current.context.get("background_findings", []),
                    *current.context.get("accepted_findings", []),
                ]
                if current is not None
                else []
            )
            summary = next(
                (
                    str(item.get("summary") or signature)
                    for item in known
                    if isinstance(item, dict) and item.get("signature") == signature
                ),
                signature,
            )
            self._connection.execute(
                """INSERT OR REPLACE INTO tsunade_accepted_log_signatures
                (source, signature, summary, accepted_at) VALUES (?,?,?,?)""",
                (source, signature, summary[:500], now.isoformat()),
            )
            if current is None:
                return
            context = {**current.context, **self._split_log_findings(source, known)}
            if not context["findings"]:
                self._resolve_log_incident(
                    current, current.last_observation_id, now, context
                )
                return
            message = (
                f"{source} : {len(context['findings'])} anomalie(s) "
                "significative(s) dans les journaux"
            )
            self._connection.execute(
                "UPDATE tsunade_incidents SET context_json=?,message=? "
                "WHERE incident_id=?",
                (
                    json.dumps(context, ensure_ascii=False, default=str),
                    message,
                    str(current.incident_id),
                ),
            )
            self._event(
                current.incident_id,
                kind="investigation",
                occurred_at=now,
                summary=f"Anomalie acceptée comme connue : {summary[:200]}",
                payload={"accepted_signature": signature},
            )

    def revoke_log_signature(self, source: str, signature: str) -> bool:
        """Count one accepted signature again from the next review."""
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM tsunade_accepted_log_signatures "
                "WHERE source=? AND signature=?",
                (source, signature),
            )
        return cursor.rowcount > 0

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

    def reviewed_log_signatures(self, incident_id: UUID | str) -> dict[str, int]:
        """Return each reviewed anomaly with the highest count already examined."""
        with self._lock:
            rows = self._connection.execute(
                """SELECT marker.key, MAX(marker.value)
                FROM tsunade_incident_events event,
                json_each(event.payload_json, '$.reviewed_log_signatures') marker
                WHERE event.incident_id=? AND marker.type='integer'
                GROUP BY marker.key""",
                (str(incident_id),),
            ).fetchall()
        return {row[0]: int(row[1]) for row in rows}

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
        if source.get("accepted_findings"):
            result += " Les anomalies restantes sont acceptées comme connues."
        if source.get("truncated") is True:
            result += " Collecte partielle : la partie analysée est saine."
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
