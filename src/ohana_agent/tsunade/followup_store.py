"""Transactional follow-up persistence used by the incident repository.

The incident repository owns the SQLite connection and its lock. Keeping the
request and execution intent in that transaction prevents an approval being
lost between the companion response and job dispatch.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from ohana_agent.tsunade.evidence_privacy import (
    redact_sensitive_text,
    redact_sensitive_value,
)


class FollowupPersistence:
    """Persistence component of TsunadeIncidentRepository, not another database."""

    _connection: Any
    _lock: Any

    def initialize_followups(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tsunade_followups (
                request_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                basis TEXT NOT NULL,
                origin_job_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                job_json TEXT,
                review_json TEXT,
                detail TEXT,
                UNIQUE(incident_id,basis)
            );
            """
        )

    def propose_followup(
        self, incident_id: str, origin_job_id: str, basis: str, plan: dict[str, Any]
    ) -> dict[str, Any] | None:
        basis = redact_sensitive_text(basis)
        plan = redact_sensitive_value(plan)
        now = datetime.now(ZoneInfo("Europe/Paris"))
        request_id = str(uuid4())
        with self._lock, self._connection:
            incident = self._connection.execute(
                "SELECT ended_at FROM tsunade_incidents WHERE incident_id=?",
                (incident_id,),
            ).fetchone()
            if incident is None or incident["ended_at"] is not None:
                return None
            existing = self._connection.execute(
                """SELECT 1 FROM tsunade_followups WHERE incident_id=? AND
                (basis=? OR origin_job_id=? OR
                 status IN ('pending','authorized','queued','reviewing'))""",
                (incident_id, basis, origin_job_id),
            ).fetchone()
            if existing:
                return None
            self._connection.execute(
                """INSERT INTO tsunade_followups
                (request_id,incident_id,basis,origin_job_id,status,created_at,plan_json)
                VALUES (?,?,?,?,'pending',?,?)""",
                (
                    request_id,
                    incident_id,
                    basis,
                    origin_job_id,
                    now.isoformat(),
                    json.dumps(plan, ensure_ascii=False),
                ),
            )
            self._connection.execute(
                """INSERT INTO tsunade_user_requests
                (request_id,incident_id,origin,kind,context,question,choices_json,
                 risk,state,created_at,expires_at,action_reference)
                VALUES (?,?,'tsunade','investigation_authorization',?,?,?,
                        'low','pending',?,?,?)""",
                (
                    request_id,
                    incident_id,
                    plan["reason"],
                    f"Autoriser une collecte ciblée des journaux de {plan['source']} ? "
                    f"Motif recherché : « {plan['pattern']} ». "
                    f"Fenêtre de deux heures, au plus {plan['max_bytes'] // 1024} Kio "
                    "lus, sans modification du système.",
                    json.dumps(["AUTHORIZE", "REFUSE", "LATER"]),
                    now.isoformat(),
                    (now + timedelta(hours=24)).isoformat(),
                    request_id,
                ),
            )
            self._event(
                UUID(incident_id),
                kind="action",
                occurred_at=now,
                summary="Une collecte complémentaire attend votre autorisation.",
                payload={
                    "request_id": request_id,
                    "operation": "logs.investigate",
                    "status": "pending",
                    "authorized": False,
                },
            )
        return self.get_followup(request_id)

    def get_followup(self, request_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM tsunade_followups WHERE request_id=?", (request_id,)
            ).fetchone()
            if row is None:
                raise LookupError("Investigation complémentaire inconnue")
            return self._followup(row)

    def unfinished_followups(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self._followup(row)
                for row in self._connection.execute(
                    """SELECT * FROM tsunade_followups
                WHERE status IN ('authorized','queued','reviewing')"""
                ).fetchall()
            ]

    def latest_followup(self, incident_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT f.*,r.state AS request_state FROM tsunade_followups f
                JOIN tsunade_user_requests r USING(request_id)
                WHERE f.incident_id=? ORDER BY julianday(f.created_at) DESC LIMIT 1""",
                (incident_id,),
            ).fetchone()
            if row is None:
                return None
            result = self._followup(row)
            if result["status"] == "pending" and row["request_state"] != "pending":
                result["status"] = row["request_state"]
            if result["status"] == "failed":
                # Read the durable transition, including legacy rows. No schema
                # migration or rewrite of historical conclusions is necessary.
                transition = self._connection.execute(
                    """SELECT occurred_at FROM tsunade_incident_events
                    WHERE incident_id=? AND kind='investigation'
                    AND json_extract(payload_json,'$.request_id')=?
                    AND json_extract(payload_json,'$.status')='failed'
                    ORDER BY event_id DESC LIMIT 1""",
                    (incident_id, result["request_id"]),
                ).fetchone()
                result["failed_at"] = transition["occurred_at"] if transition else None
            return result

    def answer_followup(
        self,
        request_id: str,
        choice: str,
        device_id: str,
        job: dict[str, Any] | None,
        *,
        automatic: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(ZoneInfo("Europe/Paris"))
        if choice not in {"AUTHORIZE", "REFUSE"}:
            raise ValueError("Cette réponse n’est pas valable pour l’investigation")
        safe_job = redact_sensitive_value(job) if job is not None else None
        with self._lock, self._connection:
            self._expire_user_requests_locked(now)
            request = self._required_pending_user_request(request_id)
            if request["kind"] != "investigation_authorization":
                raise ValueError("Cette demande ne concerne pas une investigation")
            if choice == "AUTHORIZE" and job is None:
                raise ValueError("Le plan d’investigation est indisponible")
            status = "authorized" if choice == "AUTHORIZE" else "refused"
            self._connection.execute(
                """UPDATE tsunade_followups SET status=?,job_json=?
                WHERE request_id=? AND status='pending'""",
                (
                    status,
                    json.dumps(
                        safe_job,
                        ensure_ascii=False,
                    )
                    if safe_job
                    else None,
                    request_id,
                ),
            )
            self._connection.execute(
                """UPDATE tsunade_user_requests SET state='answered',answered_at=?,
                answer=?,answer_source=?,answered_by=?,deferred_until=NULL
                WHERE request_id=?""",
                (
                    now.isoformat(),
                    choice,
                    "read_only_policy" if automatic else "shizune",
                    device_id,
                    request_id,
                ),
            )
            self._event(
                UUID(request["incident_id"]),
                kind="decision",
                occurred_at=now,
                summary=(
                    (
                        "Investigation en lecture seule autorisée par la politique."
                        if automatic
                        else "Collecte complémentaire autorisée depuis Shizune."
                    )
                    if choice == "AUTHORIZE"
                    else "Collecte complémentaire refusée."
                ),
                payload={
                    "request_id": request_id,
                    "authorized": choice == "AUTHORIZE",
                    "source": "read_only_policy" if automatic else "shizune",
                    "answered_by": device_id,
                },
            )
        return self.get_followup(request_id)

    def update_followup(
        self,
        request_id: str,
        status: str,
        detail: str,
        *,
        review: dict[str, Any] | None = None,
    ) -> None:
        detail = redact_sensitive_text(detail)
        review = redact_sensitive_value(review) if review is not None else None
        now = datetime.now(ZoneInfo("Europe/Paris"))
        with self._lock, self._connection:
            row = self.get_followup(request_id)
            if row["status"] == status and row["detail"] == detail:
                return
            self._connection.execute(
                """UPDATE tsunade_followups SET status=?,detail=?,
                review_json=COALESCE(?,review_json) WHERE request_id=?""",
                (status, detail, json.dumps(review) if review else None, request_id),
            )
            self._event(
                UUID(row["incident_id"]),
                kind="investigation",
                occurred_at=now,
                summary=detail,
                payload={"request_id": request_id, "status": status},
            )

    @staticmethod
    def _followup(
        row: Any,
    ) -> dict[str, Any]:
        value = dict(row)

        if value.get("detail"):
            value["detail"] = redact_sensitive_text(str(value["detail"]))

        if value.get("basis"):
            value["basis"] = redact_sensitive_text(str(value["basis"]))

        for key in (
            "plan",
            "job",
            "review",
        ):
            raw = value.pop(f"{key}_json")

            value[key] = redact_sensitive_value(json.loads(raw)) if raw else None

        return value
