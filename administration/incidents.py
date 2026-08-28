"""Persistent Tsunade incident lifecycle built from Shikamaru observations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
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
RepairStatus = Literal[
    "proposed", "authorized", "refused", "verifying", "succeeded", "failed"
]
ValidationSource = Literal["vision", "shizune"]
UserRequestState = Literal["pending", "answered", "expired", "cancelled", "resolved"]
UserRequestChoice = Literal["YES", "NO", "AUTHORIZE", "REFUSE", "LATER", "CONFIRM"]


class TsunadeRepair(AdministrationModel):
    """One finite repair proposal and its human authorization audit."""

    repair_id: UUID
    incident_id: UUID
    operation: Literal["restart_service"]
    target: Literal["dnsmasq.service"]
    risk: Literal["low"] = "low"
    consequences: list[str] = Field(
        default_factory=lambda: [
            "Interruption brève de la résolution DNS locale.",
            "Aucune configuration réseau n’est modifiée.",
            "Shikamaru vérifie le retour de la capacité après l’action.",
        ],
        max_length=8,
    )
    status: RepairStatus
    proposed_at: datetime
    authorized_at: datetime | None = None
    authorization_source: ValidationSource | None = None
    authorized_by: str | None = None
    executed_at: datetime | None = None
    verified_at: datetime | None = None
    result: str | None = None


class TsunadeExperience(AdministrationModel):
    """A manually confirmed diagnostic and repair experience."""

    experience_id: UUID
    signature: str
    equipment_id: str
    capability_id: str
    symptoms: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    anomalies: list[dict[str, Any]] = Field(default_factory=list)
    validated_diagnostic: str
    action: dict[str, Any]
    result: str
    occurrence_count: int = Field(ge=1)
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    last_used_at: datetime
    confidence: float = Field(ge=0, le=1)


class TsunadeExperienceCandidate(AdministrationModel):
    """A repair outcome that still requires explicit human confirmation."""

    incident_id: UUID
    prompt: str
    diagnostic: str
    action: dict[str, Any]
    result: str


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
    repairs: list[TsunadeRepair] = Field(default_factory=list)
    experience_candidate: TsunadeExperienceCandidate | None = None


class TsunadeIncidentRecordRequest(AdministrationModel):
    """A typed note; an action record never executes the action itself."""

    kind: IncidentRecordKind
    summary: str = Field(min_length=1, max_length=1000)
    payload: dict[str, Any] = Field(default_factory=dict)


class TsunadeRepairProposalRequest(AdministrationModel):
    operation: Literal["restart_service"]


class TsunadeRepairAuthorizationRequest(AdministrationModel):
    repair_id: UUID
    source: ValidationSource
    authorized_by: str = Field(default="utilisateur", min_length=1, max_length=120)


class TsunadeExperienceConfirmationRequest(AdministrationModel):
    confirm: Literal[True]
    source: ValidationSource
    confirmed_by: str = Field(default="utilisateur", min_length=1, max_length=120)


class TsunadeUserRequest(AdministrationModel):
    """One durable, synthetic decision requested by Tsunade."""

    request_id: UUID
    incident_id: UUID
    origin: Literal["tsunade"] = "tsunade"
    kind: Literal[
        "investigation_authorization",
        "repair_authorization",
        "experience_confirmation",
    ]
    context: str = Field(min_length=1, max_length=1000)
    question: str = Field(min_length=1, max_length=1000)
    choices: list[UserRequestChoice] = Field(min_length=2, max_length=6)
    risk: Literal["low", "medium", "high"] | None = None
    state: UserRequestState
    created_at: datetime
    expires_at: datetime
    deferred_until: datetime | None = None
    answered_at: datetime | None = None
    answer: UserRequestChoice | None = None
    answer_source: ValidationSource | None = None
    answered_by: str | None = None


class TsunadeUserRequestResponse(AdministrationModel):
    """A structured user response; free-form execution input is forbidden."""

    choice: UserRequestChoice
    source: ValidationSource
    answered_by: str = Field(default="utilisateur", min_length=1, max_length=120)


class TsunadeUserRequestCollection(AdministrationModel):
    """Bounded requests displayed by Vision or a companion."""

    schema_version: Literal[1] = 1
    requests: list[TsunadeUserRequest] = Field(default_factory=list)


class TsunadeCompanionActivity(AdministrationModel):
    """One human-readable timeline entry without technical payloads."""

    activity_id: str
    occurred_at: datetime
    kind: Literal["incident", "investigation", "decision", "action", "result"]
    title: str
    detail: str | None = None
    incident_id: UUID | None = None


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

    def list_user_requests(
        self,
        *,
        state: Literal["pending", "all"] = "pending",
        limit: int = 100,
    ) -> TsunadeUserRequestCollection:
        """Return bounded, lazily expired requests without incident internals."""
        if not 1 <= limit <= 200:
            raise ValueError("request limit must be between 1 and 200")
        now = datetime.now(UTC)
        condition = "state='pending'" if state == "pending" else "1=1"
        with self._lock, self._connection:
            self._expire_user_requests_locked(now)
            rows = self._connection.execute(
                f"""SELECT * FROM tsunade_user_requests WHERE {condition}
                ORDER BY (state='pending') DESC,created_at DESC LIMIT ?""",  # noqa: S608
                (limit,),
            ).fetchall()
        return TsunadeUserRequestCollection(
            requests=[self._user_request(row) for row in rows]
        )

    def get_user_request(self, request_id: UUID | str) -> TsunadeUserRequest:
        """Read one request after applying expiry rules."""
        with self._lock, self._connection:
            self._expire_user_requests_locked(datetime.now(UTC))
            return self._user_request(self._required_user_request(request_id))

    def user_request_action_reference(self, request_id: UUID | str) -> str | None:
        """Return the server-side allowlisted action reference, never client input."""
        with self._lock:
            row = self._required_user_request(request_id)
            return row["action_reference"]

    def defer_user_request(
        self,
        request_id: UUID | str,
        payload: dict[str, Any],
    ) -> TsunadeUserRequest:
        """Keep a request pending while recording a bounded one-hour deferral."""
        response = TsunadeUserRequestResponse.model_validate(payload)
        if response.choice != "LATER":
            raise ValueError("Cette réponse ne constitue pas un report")
        now = datetime.now(UTC)
        with self._lock, self._connection:
            self._expire_user_requests_locked(now)
            row = self._required_pending_user_request(request_id)
            if response.choice not in json.loads(row["choices_json"]):
                raise ValueError("Cette réponse n’est pas proposée par Tsunade")
            deferred_until = min(
                now + timedelta(hours=1), datetime.fromisoformat(row["expires_at"])
            )
            self._connection.execute(
                """UPDATE tsunade_user_requests SET deferred_until=?
                WHERE request_id=?""",
                (deferred_until.isoformat(), str(request_id)),
            )
            self._event(
                UUID(row["incident_id"]),
                kind="decision",
                occurred_at=now,
                summary="La décision a été reportée par l’utilisateur.",
                payload={
                    "request_id": str(request_id),
                    "choice": response.choice,
                    "source": response.source,
                    "answered_by": response.answered_by,
                },
            )
            return self._user_request(self._required_user_request(request_id))

    def answer_user_request(
        self,
        request_id: UUID | str,
        payload: dict[str, Any],
    ) -> TsunadeUserRequest:
        """Record one terminal structured answer after Agent handled its effect."""
        response = TsunadeUserRequestResponse.model_validate(payload)
        if response.choice == "LATER":
            return self.defer_user_request(request_id, payload)
        now = datetime.now(UTC)
        with self._lock, self._connection:
            self._expire_user_requests_locked(now)
            row = self._required_pending_user_request(request_id)
            if response.choice not in json.loads(row["choices_json"]):
                raise ValueError("Cette réponse n’est pas proposée par Tsunade")
            self._connection.execute(
                """UPDATE tsunade_user_requests SET state='answered',answered_at=?,
                answer=?,answer_source=?,answered_by=?,deferred_until=NULL
                WHERE request_id=?""",
                (
                    now.isoformat(),
                    response.choice,
                    response.source,
                    response.answered_by,
                    str(request_id),
                ),
            )
            self._event(
                UUID(row["incident_id"]),
                kind="decision",
                occurred_at=now,
                summary=f"Réponse utilisateur enregistrée : {response.choice}.",
                payload={
                    "request_id": str(request_id),
                    "choice": response.choice,
                    "source": response.source,
                    "answered_by": response.answered_by,
                },
            )
            return self._user_request(self._required_user_request(request_id))

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
        now = datetime.now(UTC)
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM tsunade_repairs WHERE repair_id=? AND incident_id=?",
                (str(repair_id), str(incident.incident_id)),
            ).fetchone()
            if row is None:
                raise LookupError("Proposition de réparation inconnue")
            if row["status"] != "proposed":
                raise ValueError("Cette réparation n’attend plus de validation")
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

    def companion_activity(self, *, limit: int = 20) -> list[TsunadeCompanionActivity]:
        """Return a deliberately synthetic subset of the incident timeline."""
        if not 1 <= limit <= 50:
            raise ValueError("activity limit must be between 1 and 50")
        with self._lock:
            rows = self._connection.execute(
                """SELECT event_id,incident_id,kind,occurred_at,summary
                FROM tsunade_incident_events
                WHERE kind IN (
                    'opened','investigation','decision','action','result','resolved'
                )
                ORDER BY occurred_at DESC,event_id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        activities: list[TsunadeCompanionActivity] = []
        for row in rows:
            kind = {
                "opened": "incident",
                "investigation": "investigation",
                "decision": "decision",
                "action": "action",
                "result": "result",
                "resolved": "result",
            }[row["kind"]]
            activities.append(
                TsunadeCompanionActivity(
                    activity_id=f"incident-event-{row['event_id']}",
                    occurred_at=datetime.fromisoformat(row["occurred_at"]),
                    kind=kind,
                    title=str(row["summary"]),
                    incident_id=row["incident_id"],
                )
            )
        return activities

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

    def propose_repair(
        self, incident_id: UUID | str, payload: dict[str, Any]
    ) -> TsunadeRepair:
        """Persist one allowlisted proposal without executing it."""
        request = TsunadeRepairProposalRequest.model_validate(payload)
        incident = self.get(incident_id)
        if incident.state != "active":
            raise ValueError("Une réparation exige un incident actif")
        identity = " ".join(
            (
                incident.node_id,
                incident.service_id,
                incident.capability_id,
                incident.message,
            )
        ).casefold()
        if request.operation != "restart_service" or not any(
            token in identity for token in ("dns", "dnsmasq")
        ):
            raise ValueError("Aucune réparation autorisée ne correspond à cet incident")
        now = datetime.now(UTC)
        with self._lock, self._connection:
            existing = self._connection.execute(
                """SELECT * FROM tsunade_repairs WHERE incident_id=?
                AND status IN ('proposed','verifying')
                ORDER BY proposed_at DESC LIMIT 1""",
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
                    request.operation,
                    "dnsmasq.service",
                    "low",
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
                        "Tsunade propose une réparation supervisée."
                    ),
                    "Autoriser le redémarrage supervisé de dnsmasq ?",
                    json.dumps(["AUTHORIZE", "REFUSE", "LATER"]),
                    "low",
                    now.isoformat(),
                    (now + timedelta(days=7)).isoformat(),
                    str(repair_id),
                ),
            )
            self._event(
                incident.incident_id,
                kind="action",
                occurred_at=now,
                summary="Tsunade propose le redémarrage supervisé de dnsmasq.",
                payload={
                    "repair_id": str(repair_id),
                    "operation": request.operation,
                    "target": "dnsmasq.service",
                    "risk": "low",
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
        now = datetime.now(UTC)
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM tsunade_repairs WHERE repair_id=? AND incident_id=?",
                (str(request.repair_id), str(incident.incident_id)),
            ).fetchone()
            if row is None:
                raise LookupError("Proposition de réparation inconnue")
            if row["status"] != "proposed":
                raise ValueError("Cette réparation n’attend plus de validation")
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

    def mark_repair_executed(self, repair_id: UUID | str) -> TsunadeRepair:
        """Move an authorized repair to Shikamaru verification."""
        now = datetime.now(UTC)
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
        now = datetime.now(UTC)
        detail = str(error)[:1000]
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
        now = datetime.now(UTC)
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
                AND capability_id=? ORDER BY last_used_at DESC LIMIT 5""",
                (incident.equipment_id, incident.capability_id),
            ).fetchall()
        return [self._experience(row) for row in rows]

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
                        "Contrôle des journaux par Katsuyu : "
                        f"{result.get('status', 'KO')}"
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
                source = {
                    **source,
                    "analyzed_at": result.get("analyzed_at"),
                    "window_started_at": result.get("window_started_at"),
                    "window_ended_at": result.get("window_ended_at"),
                }
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
                severity = "degraded"
                message = (
                    f"{source_id} : {len(findings)} anomalie(s) "
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

    def record_log_investigation(
        self, job_id: UUID | str, incident_id: UUID | str, result: dict[str, Any]
    ) -> None:
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
            CREATE INDEX IF NOT EXISTS tsunade_events_kind
            ON tsunade_incident_events(kind);
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
            CREATE TABLE IF NOT EXISTS tsunade_repairs (
                repair_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                target TEXT NOT NULL,
                risk TEXT NOT NULL,
                status TEXT NOT NULL,
                proposed_at TEXT NOT NULL,
                authorized_at TEXT,
                authorization_source TEXT,
                authorized_by TEXT,
                executed_at TEXT,
                verified_at TEXT,
                result TEXT
            );
            CREATE INDEX IF NOT EXISTS tsunade_repairs_incident
            ON tsunade_repairs(incident_id, proposed_at);
            CREATE TABLE IF NOT EXISTS tsunade_user_requests (
                request_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                origin TEXT NOT NULL,
                kind TEXT NOT NULL,
                context TEXT NOT NULL,
                question TEXT NOT NULL,
                choices_json TEXT NOT NULL,
                risk TEXT,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                deferred_until TEXT,
                answered_at TEXT,
                answer TEXT,
                answer_source TEXT,
                answered_by TEXT,
                action_reference TEXT
            );
            CREATE INDEX IF NOT EXISTS tsunade_user_requests_state
            ON tsunade_user_requests(state,created_at);
            CREATE INDEX IF NOT EXISTS tsunade_user_requests_incident
            ON tsunade_user_requests(incident_id,created_at);
            CREATE TABLE IF NOT EXISTS tsunade_experiences (
                experience_id TEXT PRIMARY KEY,
                signature TEXT NOT NULL UNIQUE,
                equipment_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                symptoms_json TEXT NOT NULL,
                context_json TEXT NOT NULL,
                observations_json TEXT NOT NULL,
                anomalies_json TEXT NOT NULL,
                validated_diagnostic TEXT NOT NULL,
                action_json TEXT NOT NULL,
                result TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL,
                success_count INTEGER NOT NULL,
                failure_count INTEGER NOT NULL,
                last_used_at TEXT NOT NULL,
                confidence REAL NOT NULL,
                confirmed_by TEXT NOT NULL,
                confirmation_source TEXT NOT NULL,
                incident_id TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tsunade_experiences_capability
            ON tsunade_experiences(equipment_id, capability_id, last_used_at);
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
        result = "La capacité est revenue à un état sain."
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
            summary=observation.message,
            payload={"from": incident.severity, "to": "healthy", "result": result},
        )
        return self.get(incident.incident_id)

    def _verify_pending_repair(
        self,
        incident: TsunadeIncident,
        observation: Observation,
        *,
        succeeded: bool,
    ) -> None:
        row = self._connection.execute(
            """SELECT * FROM tsunade_repairs WHERE incident_id=?
            AND status='verifying' ORDER BY executed_at DESC LIMIT 1""",
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
            (status, observation.timestamp.isoformat(), result, row["repair_id"]),
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
        incident = TsunadeIncident(
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
            repairs=repairs,
        )
        if include_events:
            incident.experience_candidate = self._experience_candidate(incident)
        return incident

    def _expire_user_requests_locked(self, now: datetime) -> None:
        self._connection.execute(
            """UPDATE tsunade_user_requests SET state='expired'
            WHERE state='pending' AND expires_at<=?""",
            (now.isoformat(),),
        )

    def _required_user_request(self, request_id: UUID | str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM tsunade_user_requests WHERE request_id=?",
            (str(request_id),),
        ).fetchone()
        if row is None:
            raise LookupError("Demande Tsunade inconnue")
        return row

    def _required_pending_user_request(self, request_id: UUID | str) -> sqlite3.Row:
        row = self._required_user_request(request_id)
        if row["state"] != "pending":
            raise ValueError("Cette demande Tsunade n’attend plus de réponse")
        incident = self._connection.execute(
            "SELECT ended_at FROM tsunade_incidents WHERE incident_id=?",
            (row["incident_id"],),
        ).fetchone()
        if incident is None or incident["ended_at"] is not None:
            self._connection.execute(
                "UPDATE tsunade_user_requests SET state='resolved' WHERE request_id=?",
                (str(request_id),),
            )
            raise ValueError("L’incident est déjà résolu")
        return row

    @staticmethod
    def _user_request(row: sqlite3.Row) -> TsunadeUserRequest:
        return TsunadeUserRequest(
            request_id=row["request_id"],
            incident_id=row["incident_id"],
            origin=row["origin"],
            kind=row["kind"],
            context=row["context"],
            question=row["question"],
            choices=json.loads(row["choices_json"]),
            risk=row["risk"],
            state=row["state"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            deferred_until=(
                datetime.fromisoformat(row["deferred_until"])
                if row["deferred_until"]
                else None
            ),
            answered_at=(
                datetime.fromisoformat(row["answered_at"])
                if row["answered_at"]
                else None
            ),
            answer=row["answer"],
            answer_source=row["answer_source"],
            answered_by=row["answered_by"],
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
        return TsunadeRepair(
            repair_id=row["repair_id"],
            incident_id=row["incident_id"],
            operation=row["operation"],
            target=row["target"],
            risk=row["risk"],
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
            result=row["result"],
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
            symptoms=json.loads(row["symptoms_json"]),
            context=json.loads(row["context_json"]),
            observations=json.loads(row["observations_json"]),
            anomalies=json.loads(row["anomalies_json"]),
            validated_diagnostic=row["validated_diagnostic"],
            action=json.loads(row["action_json"]),
            result=row["result"],
            occurrence_count=int(row["occurrence_count"]),
            success_count=int(row["success_count"]),
            failure_count=int(row["failure_count"]),
            last_used_at=datetime.fromisoformat(row["last_used_at"]),
            confidence=float(row["confidence"]),
        )

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
