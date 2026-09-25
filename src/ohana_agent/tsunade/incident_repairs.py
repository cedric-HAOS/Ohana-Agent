"""Repair proposals, authorizations, verification and learned experiences."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from ohana_agent.observation import Observation
from ohana_agent.tsunade.evidence_privacy import (
    redact_sensitive_text,
    redact_sensitive_value,
)
from ohana_agent.tsunade.incident_models import (
    TsunadeExperience,
    TsunadeExperienceCandidate,
    TsunadeExperienceConfirmationRequest,
    TsunadeIncident,
    TsunadeRepair,
    TsunadeRepairAuthorizationRequest,
    ValidationSource,
)
from ohana_agent.tsunade.local_time import paris_iso, paris_now
from ohana_agent.tsunade.repair_catalog import RepairSpec, repair_spec

# Shikamaru must confirm an executed repair within this delay; otherwise the
# repair ends ``unverified`` instead of waiting indefinitely in ``verifying``.
REPAIR_VERIFICATION_SECONDS = 900


class TsunadeRepairs:
    """Repair proposals, authorizations, verification and learned experiences."""

    def propose_repair(
        self, incident_id: UUID | str, spec: RepairSpec
    ) -> TsunadeRepair:
        """Persist one catalogue proposal whose preconditions were checked."""
        incident = self.get(incident_id)
        if incident.state != "active":
            raise ValueError("Une réparation exige un incident actif")
        now = paris_now()
        with self._lock, self._connection:
            existing = self._connection.execute(
                """SELECT * FROM tsunade_repairs WHERE incident_id=?
                AND status IN ('proposed','verifying')
                ORDER BY julianday(proposed_at) DESC LIMIT 1""",
                (str(incident.incident_id),),
            ).fetchone()
            if existing is not None:
                return self._repair(existing)
            repair_id = uuid4()
            self._connection.execute(
                """INSERT INTO tsunade_repairs
                (repair_id,incident_id,operation,target,risk,status,proposed_at)
                VALUES (?,?,?,?,?,'proposed',?)""",
                (
                    str(repair_id),
                    str(incident.incident_id),
                    spec.operation,
                    spec.target,
                    spec.risk,
                    now.isoformat(),
                ),
            )
            request_id = uuid4()
            self._connection.execute(
                """INSERT INTO tsunade_user_requests (
                request_id,incident_id,origin,kind,context,question,choices_json,
                risk,state,created_at,expires_at,action_reference
                ) VALUES (?,?, 'tsunade','repair_authorization',?,?,?,?,
                'pending',?,?,?)""",
                (
                    str(request_id),
                    str(incident.incident_id),
                    (
                        f"{incident.equipment_id} : {incident.message} "
                        f"Tsunade propose {spec.action}."
                    ),
                    spec.question,
                    json.dumps(["AUTHORIZE", "REFUSE", "LATER"]),
                    spec.risk,
                    now.isoformat(),
                    (now + timedelta(days=7)).isoformat(),
                    str(repair_id),
                ),
            )
            self._event(
                incident.incident_id,
                kind="action",
                occurred_at=now,
                summary=f"Tsunade propose {spec.action}.",
                payload={
                    "repair_id": str(repair_id),
                    "operation": spec.operation,
                    "target": spec.target,
                    "risk": spec.risk,
                    "status": "proposed",
                    "authorized": False,
                    "request_id": str(request_id),
                },
            )
            row = self._connection.execute(
                "SELECT * FROM tsunade_repairs WHERE repair_id=?", (str(repair_id),)
            ).fetchone()
        return self._repair(row)

    def authorize_repair(
        self, incident_id: UUID | str, payload: dict[str, Any]
    ) -> TsunadeRepair:
        """Record authorization provenance before a concrete executor runs."""
        request = TsunadeRepairAuthorizationRequest.model_validate(payload)
        incident = self.get(incident_id)
        now = paris_now()
        with self._lock, self._connection:
            self._pending_proposal_locked(request.repair_id, incident.incident_id, now)
            self._connection.execute(
                """UPDATE tsunade_repairs SET status='authorized',authorized_at=?,
                authorization_source=?,authorized_by=? WHERE repair_id=?""",
                (
                    now.isoformat(),
                    request.source,
                    request.authorized_by,
                    str(request.repair_id),
                ),
            )
            self._connection.execute(
                """UPDATE tsunade_user_requests SET state='answered',answered_at=?,
                answer='AUTHORIZE',answer_source=?,answered_by=?,deferred_until=NULL
                WHERE action_reference=? AND state='pending'""",
                (
                    now.isoformat(),
                    request.source,
                    request.authorized_by,
                    str(request.repair_id),
                ),
            )
            self._event(
                incident.incident_id,
                kind="action",
                occurred_at=now,
                summary=f"Réparation autorisée depuis {request.source.capitalize()}.",
                payload={
                    "repair_id": str(request.repair_id),
                    "authorized": True,
                    "authorization_source": request.source,
                    "authorized_by": request.authorized_by,
                },
            )
        return self.get_repair(request.repair_id)

    def refuse_repair(
        self,
        incident_id: UUID | str,
        repair_id: UUID | str,
        *,
        source: ValidationSource,
        answered_by: str,
    ) -> TsunadeRepair:
        """Record an explicit refusal without executing any operation."""
        incident = self.get(incident_id)
        now = paris_now()
        with self._lock, self._connection:
            self._pending_proposal_locked(repair_id, incident.incident_id, now)
            self._connection.execute(
                """UPDATE tsunade_repairs SET status='refused',authorized_at=?,
                authorization_source=?,authorized_by=?,result=? WHERE repair_id=?""",
                (
                    now.isoformat(),
                    source,
                    answered_by,
                    "Réparation refusée par l’utilisateur.",
                    str(repair_id),
                ),
            )
            self._connection.execute(
                """UPDATE tsunade_user_requests SET state='answered',answered_at=?,
                answer='REFUSE',answer_source=?,answered_by=?,deferred_until=NULL
                WHERE action_reference=? AND state='pending'""",
                (now.isoformat(), source, answered_by, str(repair_id)),
            )
            self._event(
                incident.incident_id,
                kind="decision",
                occurred_at=now,
                summary=f"Réparation refusée depuis {source.capitalize()}.",
                payload={
                    "repair_id": str(repair_id),
                    "authorized": False,
                    "authorization_source": source,
                    "answered_by": answered_by,
                },
            )
        return self.get_repair(repair_id)

    def mark_repair_executed(self, repair_id: UUID | str) -> TsunadeRepair:
        """Move an authorized repair to Shikamaru verification."""
        now = paris_now()
        with self._lock, self._connection:
            row = self._required_repair(repair_id)
            if row["authorized_at"] is None or row["status"] != "authorized":
                raise ValueError("La réparation n’est pas autorisée")
            self._connection.execute(
                """UPDATE tsunade_repairs SET status='verifying',executed_at=?
                WHERE repair_id=?""",
                (now.isoformat(), str(repair_id)),
            )
            self._event(
                UUID(row["incident_id"]),
                kind="action",
                occurred_at=now,
                summary=(
                    "Réparation exécutée ; Shikamaru doit maintenant "
                    "vérifier la capacité."
                ),
                payload={"repair_id": str(repair_id), "status": "verifying"},
            )
        return self.get_repair(repair_id)

    def mark_repair_execution_failed(
        self, repair_id: UUID | str, error: object
    ) -> TsunadeRepair:
        now = paris_now()
        detail = redact_sensitive_text(str(error))[:1000]
        with self._lock, self._connection:
            row = self._required_repair(repair_id)
            self._connection.execute(
                """UPDATE tsunade_repairs SET status='failed',executed_at=?,
                verified_at=?,result=? WHERE repair_id=?""",
                (now.isoformat(), now.isoformat(), detail, str(repair_id)),
            )
            self._event(
                UUID(row["incident_id"]),
                kind="result",
                occurred_at=now,
                summary=f"Échec de l’exécution de la réparation : {detail}",
                payload={"repair_id": str(repair_id), "status": "failed"},
            )
        return self.get_repair(repair_id)

    def _pending_proposal_locked(
        self, repair_id: UUID | str, incident_id: UUID, now: datetime
    ) -> sqlite3.Row:
        """Return a proposal that can still receive a human decision."""
        self._expire_repairs_locked(now)
        row = self._connection.execute(
            "SELECT * FROM tsunade_repairs WHERE repair_id=? AND incident_id=?",
            (str(repair_id), str(incident_id)),
        ).fetchone()
        if row is None:
            raise LookupError("Proposition de réparation inconnue")
        if row["status"] == "expired":
            raise ValueError(
                "Cette proposition de réparation a expiré ; aucune action n’a été "
                "exécutée"
            )
        if row["status"] != "proposed":
            raise ValueError("Cette réparation n’attend plus de validation")
        return row

    def _sweep_repairs(self, now: datetime | None = None) -> None:
        """Apply repair deadlines, reusing the caller's transaction if any."""
        with self._lock:
            if self._connection.in_transaction:
                self._expire_repairs_locked(now or paris_now())
            else:
                with self._connection:
                    self._expire_repairs_locked(now or paris_now())

    def _expire_repairs_locked(self, now: datetime) -> None:
        """Close repairs that can no longer progress, each with an explicit event."""
        # A proposal is only valid while its incident is active and its
        # authorization request is still pending: no late authorization.
        stale = self._connection.execute(
            """SELECT r.repair_id,r.incident_id,i.ended_at
            FROM tsunade_repairs r
            JOIN tsunade_incidents i ON i.incident_id=r.incident_id
            LEFT JOIN tsunade_user_requests u ON u.action_reference=r.repair_id
            WHERE r.status='proposed' AND (
                i.ended_at IS NOT NULL
                OR u.state IN ('expired','resolved','cancelled')
                OR (u.state='pending' AND julianday(u.expires_at)<=julianday(?))
            )""",
            (now.isoformat(),),
        ).fetchall()
        for row in stale:
            result = (
                "L’incident s’est résolu avant toute autorisation ; "
                "aucune action n’a été exécutée."
                if row["ended_at"] is not None
                else "La demande d’autorisation a expiré ; "
                "aucune action n’a été exécutée."
            )
            self._close_repair_locked(row, "expired", now, result, kind="decision")
        deadline = now - timedelta(seconds=REPAIR_VERIFICATION_SECONDS)
        overdue = self._connection.execute(
            """SELECT repair_id,incident_id FROM tsunade_repairs
            WHERE status='verifying' AND julianday(executed_at)<=julianday(?)""",
            (deadline.isoformat(),),
        ).fetchall()
        for row in overdue:
            self._close_repair_locked(
                row,
                "unverified",
                now,
                (
                    "Aucune observation Shikamaru n’a confirmé le résultat dans "
                    f"les {REPAIR_VERIFICATION_SECONDS // 60} minutes suivant "
                    "l’exécution. La réparation n’est pas répétée automatiquement."
                ),
                kind="result",
            )

    def _close_repair_locked(
        self,
        row: sqlite3.Row,
        status: str,
        now: datetime,
        result: str,
        *,
        kind: str,
    ) -> None:
        self._connection.execute(
            """UPDATE tsunade_repairs SET status=?,verified_at=?,result=?
            WHERE repair_id=?""",
            (status, now.isoformat(), result, row["repair_id"]),
        )
        self._connection.execute(
            """UPDATE tsunade_user_requests SET state='expired'
            WHERE action_reference=? AND state='pending'""",
            (row["repair_id"],),
        )
        self._event(
            UUID(row["incident_id"]),
            kind=kind,
            occurred_at=now,
            summary=result,
            payload={"repair_id": row["repair_id"], "status": status},
        )

    def get_repair(self, repair_id: UUID | str) -> TsunadeRepair:
        with self._lock:
            return self._repair(self._required_repair(repair_id))

    def confirm_experience(
        self, incident_id: UUID | str, payload: dict[str, Any]
    ) -> TsunadeExperience:
        """Learn only after an explicit user confirmation of a verified repair."""
        request = TsunadeExperienceConfirmationRequest.model_validate(payload)
        incident = self.get(incident_id)
        candidate = self._experience_candidate(incident)
        if candidate is None:
            raise ValueError(
                "Cet incident ne fournit aucune réparation validée à mémoriser"
            )
        signature = hashlib.sha256(
            "\0".join(
                (
                    incident.node_id,
                    incident.service_id,
                    incident.capability_id,
                    candidate.diagnostic,
                    str(candidate.action.get("operation", "")),
                    str(candidate.action.get("target", "")),
                )
            ).encode("utf-8")
        ).hexdigest()
        now = paris_now()
        anomalies = self._bounded_anomalies(incident.context)
        observations = [
            {
                "observation_id": str(event.observation_id),
                "status": event.status,
                "observed_at": event.occurred_at,
                "summary": event.summary,
            }
            for event in incident.events
            if event.observation_id is not None
        ][-32:]
        symptoms = [
            event.summary
            for event in incident.events
            if event.kind in {"opened", "observed", "escalated"}
        ][:32] or [incident.message]
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM tsunade_experiences WHERE signature=?", (signature,)
            ).fetchone()
            if existing is None:
                experience_id = uuid4()
                self._connection.execute(
                    """INSERT INTO tsunade_experiences
                    (experience_id,signature,equipment_id,capability_id,
                    symptoms_json,context_json,observations_json,anomalies_json,
                    validated_diagnostic,action_json,result,occurrence_count,
                    success_count,failure_count,last_used_at,confidence,confirmed_by,
                    confirmation_source,incident_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,1,1,0,?,1,?,?,?)""",
                    (
                        str(experience_id),
                        signature,
                        incident.equipment_id,
                        incident.capability_id,
                        json.dumps(symptoms, ensure_ascii=False),
                        json.dumps(incident.context, ensure_ascii=False, default=str),
                        json.dumps(observations, ensure_ascii=False, default=str),
                        json.dumps(anomalies, ensure_ascii=False),
                        candidate.diagnostic,
                        json.dumps(candidate.action, ensure_ascii=False),
                        candidate.result,
                        now.isoformat(),
                        request.confirmed_by,
                        request.source,
                        str(incident.incident_id),
                    ),
                )
            else:
                experience_id = UUID(existing["experience_id"])
                self._connection.execute(
                    """UPDATE tsunade_experiences
                    SET occurrence_count=occurrence_count+1,
                    success_count=success_count+1,last_used_at=?,confidence=1,
                    confirmed_by=?,confirmation_source=?,incident_id=?
                    WHERE signature=?""",
                    (
                        now.isoformat(),
                        request.confirmed_by,
                        request.source,
                        str(incident.incident_id),
                        signature,
                    ),
                )
            self._event(
                incident.incident_id,
                kind="result",
                occurred_at=now,
                summary=(
                    "Réparation enregistrée comme expérience connue "
                    "après validation humaine."
                ),
                payload={
                    "experience_id": str(experience_id),
                    "confirmation_source": request.source,
                    "confirmed_by": request.confirmed_by,
                },
            )
            row = self._connection.execute(
                "SELECT * FROM tsunade_experiences WHERE experience_id=?",
                (str(experience_id),),
            ).fetchone()
        return self._experience(row)

    def matching_experiences(
        self, incident: TsunadeIncident
    ) -> list[TsunadeExperience]:
        """Return only manually confirmed experiences for the same capability."""
        with self._lock:
            rows = self._connection.execute(
                """SELECT * FROM tsunade_experiences WHERE equipment_id=?
                AND capability_id=? ORDER BY julianday(last_used_at) DESC LIMIT 5""",
                (incident.equipment_id, incident.capability_id),
            ).fetchall()
        return [self._experience(row) for row in rows]

    def _verify_pending_repair(
        self,
        incident: TsunadeIncident,
        observation: Observation,
        *,
        succeeded: bool,
    ) -> None:
        row = self._connection.execute(
            """SELECT * FROM tsunade_repairs WHERE incident_id=?
            AND status='verifying' ORDER BY julianday(executed_at) DESC LIMIT 1""",
            (str(incident.incident_id),),
        ).fetchone()
        if row is None or observation.timestamp <= datetime.fromisoformat(
            row["executed_at"]
        ):
            return
        status = "succeeded" if succeeded else "failed"
        result = (
            "Shikamaru confirme que la capacité est redevenue saine."
            if succeeded
            else "Shikamaru observe encore une capacité dégradée après la réparation."
        )
        self._connection.execute(
            """UPDATE tsunade_repairs SET status=?,verified_at=?,result=?
            WHERE repair_id=?""",
            (status, paris_iso(observation.timestamp), result, row["repair_id"]),
        )
        self._event(
            incident.incident_id,
            kind="result",
            occurred_at=observation.timestamp,
            observation=observation,
            summary=result,
            payload={
                "repair_id": row["repair_id"],
                "status": status,
                "verified_by": "shikamaru",
            },
        )

    def _required_repair(self, repair_id: UUID | str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM tsunade_repairs WHERE repair_id=?", (str(repair_id),)
        ).fetchone()
        if row is None:
            raise LookupError("Réparation inconnue")
        return row

    @staticmethod
    def _repair(row: sqlite3.Row) -> TsunadeRepair:
        spec = repair_spec(row["operation"], row["target"])
        return TsunadeRepair(
            repair_id=row["repair_id"],
            incident_id=row["incident_id"],
            operation=row["operation"],
            target=row["target"],
            action=spec.action if spec else None,
            risk=row["risk"],
            consequences=list(spec.consequences) if spec else [],
            expected_result=spec.expected_result if spec else None,
            status=row["status"],
            proposed_at=datetime.fromisoformat(row["proposed_at"]),
            authorized_at=(
                datetime.fromisoformat(row["authorized_at"])
                if row["authorized_at"]
                else None
            ),
            authorization_source=row["authorization_source"],
            authorized_by=row["authorized_by"],
            executed_at=(
                datetime.fromisoformat(row["executed_at"])
                if row["executed_at"]
                else None
            ),
            verified_at=(
                datetime.fromisoformat(row["verified_at"])
                if row["verified_at"]
                else None
            ),
            result=(
                redact_sensitive_text(str(row["result"])) if row["result"] else None
            ),
        )

    def _experience_candidate(
        self, incident: TsunadeIncident
    ) -> TsunadeExperienceCandidate | None:
        if incident.state != "resolved":
            return None
        repair = next(
            (
                candidate
                for candidate in incident.repairs
                if candidate.status == "succeeded"
            ),
            None,
        )
        if repair is None:
            return None
        already_saved = self._connection.execute(
            "SELECT 1 FROM tsunade_experiences WHERE incident_id=? LIMIT 1",
            (str(incident.incident_id),),
        ).fetchone()
        if already_saved is not None:
            return None
        diagnostic = next(
            (
                event.summary
                for event in reversed(incident.events)
                if event.kind == "diagnostic"
                and event.payload.get("epistemic_status") == "confirmed_by_probe"
            ),
            None,
        )
        if diagnostic is None:
            return None
        return TsunadeExperienceCandidate(
            incident_id=incident.incident_id,
            prompt=(
                "Cette intervention semble avoir résolu l’incident. "
                "Enregistrer comme réparation connue ?"
            ),
            diagnostic=diagnostic,
            action={"operation": repair.operation, "target": repair.target},
            result=repair.result or incident.final_result or "Capacité saine",
        )

    @staticmethod
    def _experience(row: sqlite3.Row) -> TsunadeExperience:
        return TsunadeExperience(
            experience_id=row["experience_id"],
            signature=row["signature"],
            equipment_id=row["equipment_id"],
            capability_id=row["capability_id"],
            occurrence_count=int(row["occurrence_count"]),
            success_count=int(row["success_count"]),
            failure_count=int(row["failure_count"]),
            last_used_at=datetime.fromisoformat(row["last_used_at"]),
            confidence=float(row["confidence"]),
            symptoms=redact_sensitive_value(json.loads(row["symptoms_json"])),
            context=redact_sensitive_value(json.loads(row["context_json"])),
            observations=redact_sensitive_value(json.loads(row["observations_json"])),
            anomalies=redact_sensitive_value(json.loads(row["anomalies_json"])),
            validated_diagnostic=redact_sensitive_text(
                str(row["validated_diagnostic"])
            ),
            action=redact_sensitive_value(json.loads(row["action_json"])),
            result=redact_sensitive_text(str(row["result"])),
        )
