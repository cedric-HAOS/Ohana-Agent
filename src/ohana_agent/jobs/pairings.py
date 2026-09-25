"""Katsuyu worker pairing requests approved from Tsunade."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ohana_agent.contracts.administration import (
    DistributedWorkerPairingCollection,
    DistributedWorkerPairingCreated,
    DistributedWorkerPairingDocument,
    DistributedWorkerPairingPoll,
    DistributedWorkerPairingRequest,
    DistributedWorkerPairingResult,
)
from ohana_agent.jobs.job_types import (
    JOB_TYPE_MODELS,
    PAIRING_ALPHABET,
    DistributedJobConflictError,
)

LOGGER = logging.getLogger(__name__)


class DistributedWorkerPairings:
    """Katsuyu worker pairing requests approved from Tsunade."""

    def create_pairing(
        self, payload: dict[str, Any]
    ) -> DistributedWorkerPairingCreated:
        """Open one short-lived pairing request without issuing a credential."""
        request = DistributedWorkerPairingRequest.model_validate(payload)
        capabilities = sorted(set(request.capabilities))
        unsupported = sorted(set(capabilities) - set(JOB_TYPE_MODELS))
        if unsupported:
            raise ValueError(
                "unsupported worker capabilities: " + ", ".join(unsupported)
            )
        now = self._now()
        expires_at = now + timedelta(seconds=self.pairing_ttl_seconds)
        polling_secret = secrets.token_urlsafe(32)
        pairing_id = str(uuid4())
        code_raw = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
        verification_code = f"{code_raw[:4]}-{code_raw[4:]}"
        with self._lock, self._connection:
            self._expire_pairings_locked(now)
            existing = self._connection.execute(
                """
                SELECT 1 FROM distributed_worker_pairings
                WHERE worker_id = ? AND status IN ('PENDING', 'APPROVED')
                """,
                (request.worker_id,),
            ).fetchone()
            if existing is not None:
                raise DistributedJobConflictError(
                    "an active pairing already exists for this worker"
                )
            pending_count = self._connection.execute(
                """
                SELECT COUNT(*) FROM distributed_worker_pairings
                WHERE status IN ('PENDING', 'APPROVED')
                """
            ).fetchone()[0]
            if int(pending_count) >= self.max_pending_pairings:
                raise ValueError("worker pairing queue limit reached")
            self._connection.execute(
                """
                INSERT INTO distributed_worker_pairings (
                    pairing_id, worker_id, protocol_version, capabilities_json,
                    platform, worker_version, polling_secret_sha256,
                    verification_code, status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
                """,
                (
                    pairing_id,
                    request.worker_id,
                    request.protocol_version,
                    self._json(capabilities),
                    request.platform,
                    request.worker_version,
                    self._secret_digest(polling_secret),
                    verification_code,
                    self._timestamp(now),
                    self._timestamp(expires_at),
                ),
            )
        LOGGER.info("Worker pairing %s requested for %s", pairing_id, request.worker_id)
        return DistributedWorkerPairingCreated(
            pairing_id=pairing_id,
            polling_secret=polling_secret,
            verification_code=verification_code,
            expires_at=expires_at,
        )

    def list_pairings(self) -> DistributedWorkerPairingCollection:
        """List pairing requests without exposing polling secrets or credentials."""
        with self._lock, self._connection:
            self._expire_pairings_locked(self._now())
            rows = self._connection.execute(
                """
                SELECT * FROM distributed_worker_pairings
                ORDER BY julianday(created_at) DESC LIMIT 100
                """
            ).fetchall()
        return DistributedWorkerPairingCollection(
            pairings=[self._pairing_document(row) for row in rows]
        )

    def approve_pairing(self, pairing_id: str) -> DistributedWorkerPairingDocument:
        """Authorize credential issuance for one verified installer request."""
        now = self._now()
        with self._lock, self._connection:
            self._expire_pairings_locked(now)
            row = self._select_pairing_required_locked(pairing_id)
            if row["status"] == "APPROVED":
                return self._pairing_document(row)
            if row["status"] != "PENDING":
                raise DistributedJobConflictError(
                    f"pairing cannot be approved from {row['status']}"
                )
            self._connection.execute(
                """
                UPDATE distributed_worker_pairings
                SET status = 'APPROVED', approved_at = ? WHERE pairing_id = ?
                """,
                (self._timestamp(now), pairing_id),
            )
            row = self._select_pairing_required_locked(pairing_id)
        LOGGER.info("Worker pairing %s approved", pairing_id)
        return self._pairing_document(row)

    def reject_pairing(self, pairing_id: str) -> DistributedWorkerPairingDocument:
        """Reject a request so its polling secret can never obtain a credential."""
        now = self._now()
        with self._lock, self._connection:
            self._expire_pairings_locked(now)
            row = self._select_pairing_required_locked(pairing_id)
            if row["status"] == "REJECTED":
                return self._pairing_document(row)
            if row["status"] not in {"PENDING", "APPROVED"}:
                raise DistributedJobConflictError(
                    f"pairing cannot be rejected from {row['status']}"
                )
            self._connection.execute(
                """
                UPDATE distributed_worker_pairings
                SET status = 'REJECTED' WHERE pairing_id = ?
                """,
                (pairing_id,),
            )
            row = self._select_pairing_required_locked(pairing_id)
        LOGGER.info("Worker pairing %s rejected", pairing_id)
        return self._pairing_document(row)

    def poll_pairing(
        self, pairing_id: str, payload: dict[str, Any]
    ) -> DistributedWorkerPairingResult:
        """Return state and issue one per-worker bearer credential exactly once."""
        poll = DistributedWorkerPairingPoll.model_validate(payload)
        now = self._now()
        worker_token: str | None = None
        with self._lock, self._connection:
            self._expire_pairings_locked(now)
            row = self._select_pairing_required_locked(pairing_id)
            if not hmac.compare_digest(
                row["polling_secret_sha256"],
                self._secret_digest(poll.polling_secret),
            ):
                raise LookupError("worker pairing not found")
            if row["status"] == "APPROVED":
                worker_token = secrets.token_urlsafe(48)
                self._connection.execute(
                    """
                    INSERT INTO distributed_worker_credentials (
                        worker_id, token_sha256, created_at, revoked_at
                    ) VALUES (?, ?, ?, NULL)
                    ON CONFLICT(worker_id) DO UPDATE SET
                        token_sha256 = excluded.token_sha256,
                        created_at = excluded.created_at,
                        revoked_at = NULL
                    """,
                    (
                        row["worker_id"],
                        self._secret_digest(worker_token),
                        self._timestamp(now),
                    ),
                )
                self._connection.execute(
                    """
                    UPDATE distributed_worker_pairings
                    SET status = 'CONSUMED', consumed_at = ? WHERE pairing_id = ?
                    """,
                    (self._timestamp(now), pairing_id),
                )
                row = self._select_pairing_required_locked(pairing_id)
        return DistributedWorkerPairingResult(
            pairing_id=row["pairing_id"],
            status=row["status"],
            expires_at=self._parse_timestamp(row["expires_at"]),
            worker_token=worker_token,
        )

    def _expire_pairings_locked(self, now: datetime) -> None:
        self._connection.execute(
            """
            UPDATE distributed_worker_pairings SET status = 'EXPIRED'
            WHERE status IN ('PENDING', 'APPROVED') AND expires_at <= ?
            """,
            (self._timestamp(now),),
        )

    def _select_pairing_required_locked(self, pairing_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM distributed_worker_pairings WHERE pairing_id = ?",
            (pairing_id,),
        ).fetchone()
        if row is None:
            raise LookupError("worker pairing not found")
        return row

    def _pairing_document(self, row: sqlite3.Row) -> DistributedWorkerPairingDocument:
        return DistributedWorkerPairingDocument(
            pairing_id=row["pairing_id"],
            protocol_version=row["protocol_version"],
            worker_id=row["worker_id"],
            capabilities=json.loads(row["capabilities_json"]),
            platform=row["platform"],
            worker_version=row["worker_version"],
            verification_code=row["verification_code"],
            status=row["status"],
            created_at=self._parse_timestamp(row["created_at"]),
            expires_at=self._parse_timestamp(row["expires_at"]),
        )

    @staticmethod
    def _secret_digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
