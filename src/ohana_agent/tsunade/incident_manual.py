"""Manual resolutions declared by the user and verified by Shikamaru."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from ohana_agent.observation import Observation
from ohana_agent.tsunade.evidence_privacy import redact_sensitive_text
from ohana_agent.tsunade.incident_models import (
    TsunadeIncident,
    TsunadeManualAction,
    TsunadeManualResolutionRequest,
)
from ohana_agent.tsunade.local_time import paris_iso, paris_now

# A service the user just fixed may still be starting: a degraded observation
# this soon after the declaration does not reject it; a healthy one confirms.
MANUAL_SETTLE_SECONDS = 60
# A user who fixed the service before declaring it can lose the race: the
# incident closes as soon as Shikamaru sees the recovery. Konoha, 28
# September: teleinfo2mqtt restarted, incident resolved before the form was
# sent. The declaration stays possible this long after the resolution.
MANUAL_LATE_DECLARATION_SECONDS = 600


class TsunadeManualResolutions:
    """Manual resolutions declared by the user and verified by Shikamaru.

    The description is a note for the user: Ohana never parses nor executes
    it, whatever it contains.
    """

    def declare_manual_resolution(
        self, incident_id: UUID | str, payload: dict[str, Any]
    ) -> TsunadeManualAction:
        """Record what the user did; Shikamaru must still confirm the result."""
        request = TsunadeManualResolutionRequest.model_validate(payload)
        now = paris_now()
        with self._lock, self._connection:
            row = self._connection.execute(
                """SELECT ended_at,last_observation_id FROM tsunade_incidents
                WHERE incident_id=?""",
                (str(incident_id),),
            ).fetchone()
            if row is None:
                raise LookupError(f"Unknown incident: {incident_id}")
            if row["ended_at"] is not None:
                return self._declare_after_resolution_locked(
                    str(incident_id), row, request, now
                )
            pending = self._connection.execute(
                """SELECT 1 FROM tsunade_manual_actions
                WHERE incident_id=? AND status='verifying' LIMIT 1""",
                (str(incident_id),),
            ).fetchone()
            if pending is not None:
                raise ValueError(
                    "Une action manuelle attend déjà la vérification de Shikamaru"
                )
            delay = self._verification_seconds_locked(str(incident_id))
            action_id = uuid4()
            description = redact_sensitive_text(request.description.strip())
            self._connection.execute(
                """INSERT INTO tsunade_manual_actions
                (action_id,incident_id,description,declared_at,declared_by,source,
                status,verification_deadline)
                VALUES (?,?,?,?,?,?,'verifying',?)""",
                (
                    str(action_id),
                    str(incident_id),
                    description,
                    now.isoformat(),
                    request.declared_by,
                    request.source,
                    (now + timedelta(seconds=delay)).isoformat(),
                ),
            )
            self._event(
                UUID(str(incident_id)),
                kind="action",
                occurred_at=now,
                summary=(
                    f"Action manuelle déclarée : « {description} ». Ohana "
                    "n’exécute rien ; Shikamaru doit vérifier le retour à l’état "
                    "sain."
                ),
                payload={
                    "manual_action_id": str(action_id),
                    "status": "verifying",
                    "verification_seconds": delay,
                },
            )
            action = self._connection.execute(
                "SELECT * FROM tsunade_manual_actions WHERE action_id=?",
                (str(action_id),),
            ).fetchone()
        return self._manual_action(action)

    def _declare_after_resolution_locked(
        self,
        incident_id: str,
        incident: sqlite3.Row,
        request: TsunadeManualResolutionRequest,
        now: datetime,
    ) -> TsunadeManualAction:
        """Record an action declared just after Shikamaru saw the recovery."""
        ended_at = datetime.fromisoformat(incident["ended_at"])
        if now - ended_at > timedelta(seconds=MANUAL_LATE_DECLARATION_SECONDS):
            raise ValueError(
                "Une résolution manuelle se déclare au plus tard 10 minutes "
                "après la résolution de l’incident"
            )
        if self._connection.execute(
            "SELECT 1 FROM tsunade_manual_actions WHERE incident_id=? LIMIT 1",
            (incident_id,),
        ).fetchone():
            raise ValueError("Une action manuelle est déjà déclarée sur cet incident")
        if self._connection.execute(
            """SELECT 1 FROM tsunade_repairs WHERE incident_id=?
            AND status='succeeded' LIMIT 1""",
            (incident_id,),
        ).fetchone():
            raise ValueError(
                "Cet incident a été résolu par une réparation supervisée vérifiée"
            )
        action_id = uuid4()
        description = redact_sensitive_text(request.description.strip())
        result = (
            f"Shikamaru avait constaté le retour à l’état sain le "
            f"{ended_at:%d/%m/%Y à %H:%M:%S}, avant cette déclaration. Cette "
            "succession ne prouve pas à elle seule que l’action en est la cause."
        )
        self._connection.execute(
            """INSERT INTO tsunade_manual_actions
            (action_id,incident_id,description,declared_at,declared_by,source,
            status,verification_deadline,verified_at,result,observation_id)
            VALUES (?,?,?,?,?,?,'confirmed',?,?,?,?)""",
            (
                str(action_id),
                incident_id,
                description,
                now.isoformat(),
                request.declared_by,
                request.source,
                now.isoformat(),
                ended_at.isoformat(),
                result,
                incident["last_observation_id"],
            ),
        )
        self._event(
            UUID(incident_id),
            kind="action",
            occurred_at=now,
            summary=(
                f"Action manuelle déclarée après la résolution : « {description} ». "
                "Ohana n’exécute rien."
            ),
            payload={"manual_action_id": str(action_id), "status": "confirmed"},
        )
        action = self._connection.execute(
            "SELECT * FROM tsunade_manual_actions WHERE action_id=?",
            (str(action_id),),
        ).fetchone()
        return self._manual_action(action)

    def _verify_manual_action(
        self,
        incident: TsunadeIncident,
        observation: Observation,
        *,
        succeeded: bool,
    ) -> None:
        row = self._connection.execute(
            """SELECT * FROM tsunade_manual_actions WHERE incident_id=?
            AND status='verifying' ORDER BY julianday(declared_at) DESC LIMIT 1""",
            (str(incident.incident_id),),
        ).fetchone()
        if row is None:
            return
        declared_at = datetime.fromisoformat(row["declared_at"])
        if observation.timestamp <= declared_at:
            return
        if not succeeded and observation.timestamp < declared_at + timedelta(
            seconds=MANUAL_SETTLE_SECONDS
        ):
            return
        status = "confirmed" if succeeded else "unconfirmed"
        result = (
            "Shikamaru observe un retour à l’état sain après l’action déclarée. "
            "Cette succession ne prouve pas à elle seule que l’action en est "
            "la cause."
            if succeeded
            else "Shikamaru observe encore une capacité dégradée après l’action "
            "déclarée."
        )
        self._close_manual_action_locked(
            row,
            status,
            datetime.fromisoformat(paris_iso(observation.timestamp)),
            result,
            observation=observation,
        )

    def _expire_manual_actions_locked(self, now: datetime) -> None:
        overdue = self._connection.execute(
            """SELECT * FROM tsunade_manual_actions WHERE status='verifying'
            AND julianday(verification_deadline)<=julianday(?)""",
            (now.isoformat(),),
        ).fetchall()
        for row in overdue:
            self._close_manual_action_locked(
                row,
                "unconfirmed",
                now,
                "Aucune observation Shikamaru n’a confirmé le retour à l’état sain "
                "après l’action déclarée.",
            )

    def _close_manual_action_locked(
        self,
        row: sqlite3.Row,
        status: str,
        at: datetime,
        result: str,
        *,
        observation: Observation | None = None,
    ) -> None:
        self._connection.execute(
            """UPDATE tsunade_manual_actions SET status=?,verified_at=?,result=?,
            observation_id=? WHERE action_id=?""",
            (
                status,
                at.isoformat(),
                result,
                str(observation.id) if observation is not None else None,
                row["action_id"],
            ),
        )
        self._event(
            UUID(row["incident_id"]),
            kind="result",
            occurred_at=at,
            observation=observation,
            summary=result,
            payload={
                "manual_action_id": row["action_id"],
                "status": status,
                "verified_by": "shikamaru",
            },
        )

    def _manual_actions_locked(self, incident_id: str) -> list[TsunadeManualAction]:
        rows = self._connection.execute(
            """SELECT * FROM tsunade_manual_actions WHERE incident_id=?
            ORDER BY julianday(declared_at) DESC LIMIT 10""",
            (incident_id,),
        ).fetchall()
        return [self._manual_action(row) for row in rows]

    @staticmethod
    def _manual_action(row: sqlite3.Row) -> TsunadeManualAction:
        def moment(name: str) -> datetime | None:
            return datetime.fromisoformat(row[name]) if row[name] else None

        return TsunadeManualAction(
            action_id=row["action_id"],
            incident_id=row["incident_id"],
            description=redact_sensitive_text(str(row["description"])),
            declared_at=datetime.fromisoformat(row["declared_at"]),
            declared_by=row["declared_by"],
            source=row["source"],
            status=row["status"],
            verification_deadline=moment("verification_deadline"),
            verified_at=moment("verified_at"),
            result=row["result"],
        )
