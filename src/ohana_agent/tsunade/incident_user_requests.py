"""Questions Tsunade asks the companion, and the answers it records."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from ohana_agent.tsunade.evidence_privacy import (
    redact_sensitive_text,
)
from ohana_agent.tsunade.incident_models import (
    TsunadeCompanionActivity,
    TsunadeUserRequest,
    TsunadeUserRequestCollection,
    TsunadeUserRequestResponse,
)


class TsunadeUserRequests:
    """Questions Tsunade asks the companion, and the answers it records."""

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
                    title=redact_sensitive_text(str(row["summary"])),
                    incident_id=row["incident_id"],
                )
            )
        return activities

    def _expire_user_requests_locked(self, now: datetime) -> None:
        self._connection.execute(
            """UPDATE tsunade_user_requests SET state='expired'
            WHERE state='pending' AND julianday(expires_at)<=julianday(?)""",
            (now.isoformat(),),
        )
        self._connection.execute(
            """UPDATE tsunade_followups SET status=(SELECT state
            FROM tsunade_user_requests r
            WHERE r.request_id=tsunade_followups.request_id)
            WHERE status='pending' AND request_id IN
            (SELECT request_id FROM tsunade_user_requests WHERE state!='pending')"""
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
            context=redact_sensitive_text(str(row["context"])),
            question=redact_sensitive_text(str(row["question"])),
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
