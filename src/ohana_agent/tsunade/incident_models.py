"""Tsunade incident, repair, experience and user-request documents."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from ohana_agent.contracts.administration import AdministrationModel
from ohana_agent.tsunade.local_time import ParisDatetime

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
    "proposed",
    "authorized",
    "refused",
    "expired",
    "verifying",
    "succeeded",
    "failed",
    "unverified",
]
ValidationSource = Literal["vision", "shizune"]
UserRequestState = Literal["pending", "answered", "expired", "cancelled", "resolved"]
UserRequestChoice = Literal["YES", "NO", "AUTHORIZE", "REFUSE", "LATER", "CONFIRM"]


class TsunadeRepair(AdministrationModel):
    """One finite repair proposal and its human authorization audit."""

    repair_id: UUID
    incident_id: UUID
    operation: Literal["restart_service", "restart_addon"]
    target: str = Field(min_length=1, max_length=120)
    action: str | None = None
    risk: Literal["low", "medium", "high"] = "low"
    consequences: list[str] = Field(default_factory=list, max_length=8)
    expected_result: str | None = None
    status: RepairStatus
    proposed_at: ParisDatetime
    authorized_at: ParisDatetime | None = None
    authorization_source: ValidationSource | None = None
    authorized_by: str | None = None
    executed_at: ParisDatetime | None = None
    verified_at: ParisDatetime | None = None
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
    last_used_at: ParisDatetime
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
    occurred_at: ParisDatetime
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
    started_at: ParisDatetime
    last_observed_at: ParisDatetime
    ended_at: ParisDatetime | None = None
    last_observation_id: UUID
    message: str
    occurrence_count: int = Field(ge=1)
    recurrence_count: int = Field(ge=0)
    context: dict[str, Any] = Field(default_factory=dict)
    latest_decision: dict[str, Any] | None = None
    final_result: str | None = None
    events: list[TsunadeIncidentEvent] = Field(default_factory=list)
    repairs: list[TsunadeRepair] = Field(default_factory=list)
    experience_candidate: TsunadeExperienceCandidate | None = None
    followup: dict[str, Any] | None = None


class TsunadeIncidentRecordRequest(AdministrationModel):
    """A typed note; an action record never executes the action itself."""

    kind: IncidentRecordKind
    summary: str = Field(min_length=1, max_length=1000)
    payload: dict[str, Any] = Field(default_factory=dict)


class TsunadeRepairProposalRequest(AdministrationModel):
    """Ask Tsunade for its catalogue repair; the client never names a target."""

    operation: Literal["restart_service", "restart_addon"] | None = None


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
    created_at: ParisDatetime
    expires_at: ParisDatetime
    deferred_until: ParisDatetime | None = None
    answered_at: ParisDatetime | None = None
    answer: UserRequestChoice | None = None
    answer_source: Literal["vision", "shizune", "read_only_policy"] | None = None
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
    occurred_at: ParisDatetime
    kind: Literal["incident", "investigation", "decision", "action", "result"]
    title: str
    detail: str | None = None
    incident_id: UUID | None = None
