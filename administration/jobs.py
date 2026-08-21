"""Durable, leased and explicitly typed jobs coordinated by Ohana-Agent."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from administration.models import (
    BackupCompressParameters,
    BackupCompressResult,
    BackupEncryptParameters,
    BackupEncryptResult,
    BackupVerifyParameters,
    BackupVerifyResult,
    DistributedJobClaim,
    DistributedJobClaimResult,
    DistributedJobCompletion,
    DistributedJobCreate,
    DistributedJobDocument,
    DistributedJobHeartbeat,
    DistributedJobStatus,
    DistributedWorkerAvailability,
    DistributedWorkerCollection,
    DistributedWorkerDocument,
    DistributedWorkerPairingCollection,
    DistributedWorkerPairingCreated,
    DistributedWorkerPairingDocument,
    DistributedWorkerPairingPoll,
    DistributedWorkerPairingRequest,
    DistributedWorkerPairingResult,
    DistributedWorkerRegistration,
    InfraBackupParameters,
    InfraBackupResult,
    SystemHealthParameters,
    SystemHealthResult,
)

LOGGER = logging.getLogger(__name__)
TERMINAL_STATUSES = {
    DistributedJobStatus.SUCCEEDED,
    DistributedJobStatus.FAILED,
    DistributedJobStatus.CANCELLED,
    DistributedJobStatus.TIMEOUT,
}
JOB_TYPE_MODELS: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "system.health": (
        SystemHealthParameters,
        SystemHealthResult,
    ),
    "backup.compress": (BackupCompressParameters, BackupCompressResult),
    "backup.encrypt": (BackupEncryptParameters, BackupEncryptResult),
    "backup.verify": (BackupVerifyParameters, BackupVerifyResult),
    "backup.infra": (InfraBackupParameters, InfraBackupResult),
}
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class DistributedJobConflictError(RuntimeError):
    """Raised when a job operation conflicts with its durable state."""


class DistributedJobRepository:
    """Persist jobs, leases and transitions in a small local SQLite database."""

    def __init__(
        self,
        path: Path,
        *,
        lease_seconds: int = 60,
        waiting_worker_after_seconds: int = 30,
        retention_days: int = 30,
        max_active_jobs: int = 1000,
        pairing_ttl_seconds: int = 600,
        max_pending_pairings: int = 10,
        worker_available_seconds: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if lease_seconds < 10:
            raise ValueError("lease_seconds must be at least 10")
        if waiting_worker_after_seconds < 0:
            raise ValueError("waiting_worker_after_seconds cannot be negative")
        if retention_days < 1:
            raise ValueError("retention_days must be at least one")
        if max_active_jobs < 1:
            raise ValueError("max_active_jobs must be at least one")
        if pairing_ttl_seconds < 60 or pairing_ttl_seconds > 3600:
            raise ValueError("pairing_ttl_seconds must be between 60 and 3600")
        if max_pending_pairings < 1 or max_pending_pairings > 100:
            raise ValueError("max_pending_pairings must be between 1 and 100")
        if worker_available_seconds < 10 or worker_available_seconds > 600:
            raise ValueError("worker_available_seconds must be between 10 and 600")

        self.path = path
        self.lease_seconds = lease_seconds
        self.waiting_worker_after_seconds = waiting_worker_after_seconds
        self.retention_days = retention_days
        self.max_active_jobs = max_active_jobs
        self.pairing_ttl_seconds = pairing_ttl_seconds
        self.max_pending_pairings = max_pending_pairings
        self.worker_available_seconds = worker_available_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = Lock()
        if path != Path(":memory:"):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    @property
    def supported_types(self) -> tuple[str, ...]:
        """Return the finite protocol allowlist understood by this Agent."""
        return tuple(JOB_TYPE_MODELS)

    def close(self) -> None:
        """Close the durable store after pending transactions are committed."""
        with self._lock:
            self._connection.close()

    def create(self, payload: dict[str, Any]) -> DistributedJobDocument:
        """Validate and durably enqueue one idempotent Tsunade request."""
        request = DistributedJobCreate.model_validate(payload)
        parameters = self._validate_parameters(request.type, request.parameters)
        normalized = request.model_copy(update={"parameters": parameters})
        request_sha256 = self._digest(normalized.model_dump(mode="json"))
        now = self._now()
        created_at = request.created_at.astimezone(UTC)
        if created_at > now + timedelta(minutes=5):
            raise ValueError(
                "created_at cannot be more than five minutes in the future"
            )
        if created_at + timedelta(seconds=request.timeout) <= now:
            raise ValueError("job timeout has already elapsed")

        with self._lock, self._connection:
            self._recover_locked(now)
            existing = self._select_locked(str(request.job_id))
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    raise DistributedJobConflictError(
                        "job_id already exists with a different request"
                    )
                return self._document(existing)

            active_count = self._connection.execute(
                """
                SELECT COUNT(*) FROM distributed_jobs
                WHERE status NOT IN (?, ?, ?, ?)
                """,
                tuple(status.value for status in TERMINAL_STATUSES),
            ).fetchone()[0]
            if int(active_count) >= self.max_active_jobs:
                raise ValueError("distributed job active queue limit reached")

            values = (
                str(request.job_id),
                request.protocol_version,
                request.type,
                self._timestamp(created_at),
                self._json(parameters),
                request.timeout,
                DistributedJobStatus.QUEUED.value,
                request_sha256,
                self._timestamp(now),
            )
            self._connection.execute(
                """
                INSERT INTO distributed_jobs (
                    job_id, protocol_version, type, created_at, parameters_json,
                    timeout_seconds, status, request_sha256, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            self._event_locked(
                str(request.job_id),
                None,
                DistributedJobStatus.CREATED,
                now,
                "accepted",
            )
            self._event_locked(
                str(request.job_id),
                DistributedJobStatus.CREATED,
                DistributedJobStatus.QUEUED,
                now,
                "queued",
            )
            LOGGER.info("Distributed job %s queued (%s)", request.job_id, request.type)
            return self._document(self._select_required_locked(str(request.job_id)))

    def get(self, job_id: str) -> DistributedJobDocument:
        """Read one job after applying due timeout and lease recovery."""
        with self._lock, self._connection:
            self._recover_locked(self._now())
            return self._document(self._select_required_locked(job_id))

    def cancel(self, job_id: str) -> DistributedJobDocument:
        """Cancel a non-terminal job; repeated cancellation is idempotent."""
        now = self._now()
        with self._lock, self._connection:
            self._recover_locked(now)
            row = self._select_required_locked(job_id)
            current = DistributedJobStatus(row["status"])
            if current == DistributedJobStatus.CANCELLED:
                return self._document(row)
            if current in TERMINAL_STATUSES:
                raise DistributedJobConflictError(
                    f"job is already terminal with status {current.value}"
                )
            self._transition_locked(
                row,
                DistributedJobStatus.CANCELLED,
                now,
                detail="cancelled by Tsunade",
                finished_at=now,
                clear_lease=True,
            )
            return self._document(self._select_required_locked(job_id))

    def claim(self, payload: dict[str, Any]) -> DistributedJobClaimResult:
        """Atomically lease the oldest compatible job to Katsuyu."""
        claim = DistributedJobClaim.model_validate(payload)
        compatible_types = [
            job_type
            for job_type in claim.supported_types
            if job_type in JOB_TYPE_MODELS
        ]
        if not compatible_types:
            return DistributedJobClaimResult(job=None)

        now = self._now()
        placeholders = ",".join("?" for _ in compatible_types)
        with self._lock, self._connection:
            self._recover_locked(now)
            self._touch_worker_locked(claim.worker_id, now)
            row = self._connection.execute(
                f"""
                SELECT * FROM distributed_jobs
                WHERE status IN (?, ?) AND type IN ({placeholders})
                ORDER BY created_at ASC, job_id ASC
                LIMIT 1
                """,  # noqa: S608 - placeholders are generated, values remain bound.
                (
                    DistributedJobStatus.QUEUED.value,
                    DistributedJobStatus.WAITING_WORKER.value,
                    *compatible_types,
                ),
            ).fetchone()
            if row is None:
                return DistributedJobClaimResult(job=None)

            deadline = self._deadline(row)
            lease_expires_at = min(
                deadline,
                now + timedelta(seconds=self.lease_seconds),
            )
            attempt = int(row["attempt"]) + 1
            self._connection.execute(
                """
                UPDATE distributed_jobs
                SET status = ?, started_at = COALESCE(started_at, ?),
                    worker_id = ?, attempt = ?, lease_expires_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    DistributedJobStatus.RUNNING.value,
                    self._timestamp(now),
                    claim.worker_id,
                    attempt,
                    self._timestamp(lease_expires_at),
                    self._timestamp(now),
                    row["job_id"],
                ),
            )
            self._event_locked(
                row["job_id"],
                DistributedJobStatus(row["status"]),
                DistributedJobStatus.RUNNING,
                now,
                f"claimed by {claim.worker_id}; attempt {attempt}",
            )
            LOGGER.info(
                "Distributed job %s claimed by %s (attempt %s)",
                row["job_id"],
                claim.worker_id,
                attempt,
            )
            document = self._document(self._select_required_locked(row["job_id"]))
            return DistributedJobClaimResult(job=document)

    def register_worker(self, payload: dict[str, Any]) -> DistributedWorkerDocument:
        """Persist one authenticated worker identity and finite capability list."""
        registration = DistributedWorkerRegistration.model_validate(payload)
        capabilities = sorted(set(registration.capabilities))
        unsupported = sorted(set(capabilities) - set(JOB_TYPE_MODELS))
        if unsupported:
            raise ValueError(
                "unsupported worker capabilities: " + ", ".join(unsupported)
            )
        now = self._now()
        normalized = registration.model_copy(update={"capabilities": capabilities})
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM distributed_workers WHERE worker_id = ?",
                (normalized.worker_id,),
            ).fetchone()
            registered_at = (
                self._parse_timestamp(existing["registered_at"]) if existing else now
            )
            existing_wake_deadline = (
                self._parse_timestamp(existing["wake_deadline_at"])
                if existing and existing["wake_deadline_at"]
                else None
            )
            waking = bool(existing_wake_deadline and existing_wake_deadline >= now)
            woken_by_ohana = bool(existing and existing["woken_by_ohana"] and waking)
            wake_requested_at = (
                existing["wake_requested_at"] if woken_by_ohana else None
            )
            wake_deadline_at = existing["wake_deadline_at"] if woken_by_ohana else None
            self._connection.execute(
                """
                INSERT INTO distributed_workers (
                    worker_id, protocol_version, capabilities_json, platform,
                    worker_version, registered_at, last_seen_at, woken_by_ohana,
                    wake_requested_at, wake_deadline_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    protocol_version = excluded.protocol_version,
                    capabilities_json = excluded.capabilities_json,
                    platform = excluded.platform,
                    worker_version = excluded.worker_version,
                    last_seen_at = excluded.last_seen_at,
                    woken_by_ohana = excluded.woken_by_ohana,
                    wake_requested_at = excluded.wake_requested_at,
                    wake_deadline_at = excluded.wake_deadline_at
                """,
                (
                    normalized.worker_id,
                    normalized.protocol_version,
                    self._json(capabilities),
                    normalized.platform,
                    normalized.worker_version,
                    self._timestamp(registered_at),
                    self._timestamp(now),
                    woken_by_ohana,
                    wake_requested_at,
                    wake_deadline_at,
                ),
            )
        LOGGER.info(
            "Katsuyu worker %s registered (%s)",
            normalized.worker_id,
            ", ".join(capabilities),
        )
        return DistributedWorkerDocument(
            **normalized.model_dump(),
            registered_at=registered_at,
            last_seen_at=now,
            availability=DistributedWorkerAvailability.AVAILABLE,
            woken_by_ohana=woken_by_ohana,
            wake_requested_at=(
                self._parse_timestamp(wake_requested_at) if wake_requested_at else None
            ),
            wake_deadline_at=(
                self._parse_timestamp(wake_deadline_at) if wake_deadline_at else None
            ),
        )

    def list_workers(self) -> DistributedWorkerCollection:
        """Return the latest authenticated registrations to Tsunade."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM distributed_workers ORDER BY worker_id"
            ).fetchall()
        now = self._now()
        return DistributedWorkerCollection(
            workers=[self._worker_document(row, now) for row in rows]
        )

    def mark_worker_waking(
        self,
        worker_id: str,
        *,
        timeout_seconds: int,
    ) -> DistributedWorkerDocument:
        """Persist that Ohana sent WOL for a known, currently unavailable worker."""
        if timeout_seconds < 10 or timeout_seconds > 1800:
            raise ValueError("wake timeout must be between 10 and 1800 seconds")
        now = self._now()
        deadline = now + timedelta(seconds=timeout_seconds)
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM distributed_workers WHERE worker_id = ?",
                (worker_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"distributed worker not found: {worker_id}")
            document = self._worker_document(row, now)
            if document.availability == DistributedWorkerAvailability.AVAILABLE:
                return document
            self._connection.execute(
                """
                UPDATE distributed_workers
                SET woken_by_ohana = 1, wake_requested_at = ?, wake_deadline_at = ?
                WHERE worker_id = ?
                """,
                (self._timestamp(now), self._timestamp(deadline), worker_id),
            )
            updated = self._connection.execute(
                "SELECT * FROM distributed_workers WHERE worker_id = ?",
                (worker_id,),
            ).fetchone()
        LOGGER.info("Katsuyu worker %s is waking after an Ohana WOL request", worker_id)
        return self._worker_document(updated, now)

    def worker_supports(self, worker_id: str, job_type: str) -> bool:
        """Return whether a previously registered worker announced a job type."""
        with self._lock:
            row = self._connection.execute(
                "SELECT capabilities_json FROM distributed_workers WHERE worker_id = ?",
                (worker_id,),
            ).fetchone()
        return bool(row and job_type in json.loads(row["capabilities_json"]))

    def worker_availability(self, worker_id: str) -> DistributedWorkerDocument:
        """Return the current computed availability of one worker."""
        now = self._now()
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM distributed_workers WHERE worker_id = ?",
                (worker_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"distributed worker not found: {worker_id}")
        return self._worker_document(row, now)

    def authorize_job_transfer(
        self,
        job_id: str,
        *,
        worker_id: str,
        attempt: int,
        job_type: str = "backup.infra",
    ) -> DistributedJobDocument:
        """Authorize a bounded transfer for the worker owning a running job."""
        now = self._now()
        with self._lock, self._connection:
            self._recover_locked(now)
            row = self._select_required_locked(job_id)
            self._require_owner(row, worker_id, attempt)
            if row["type"] != job_type:
                raise DistributedJobConflictError(
                    f"job type does not permit this transfer: {row['type']}"
                )
            self._touch_worker_locked(worker_id, now)
            return self._document(row)

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
                ORDER BY created_at DESC LIMIT 100
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

    def authorize_worker(self, worker_id: str, token: str) -> bool:
        """Validate a per-worker bearer credential without storing its clear text."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT token_sha256 FROM distributed_worker_credentials
                WHERE worker_id = ? AND revoked_at IS NULL
                """,
                (worker_id,),
            ).fetchone()
        return row is not None and hmac.compare_digest(
            row["token_sha256"], self._secret_digest(token)
        )

    def heartbeat(
        self,
        job_id: str,
        payload: dict[str, Any],
    ) -> DistributedJobDocument:
        """Renew a lease only for the worker and attempt that own it."""
        heartbeat = DistributedJobHeartbeat.model_validate(payload)
        now = self._now()
        with self._lock, self._connection:
            self._recover_locked(now)
            row = self._select_required_locked(job_id)
            current = DistributedJobStatus(row["status"])
            if current in {
                DistributedJobStatus.CANCELLED,
                DistributedJobStatus.TIMEOUT,
            }:
                self._require_attempt_owner(
                    row,
                    heartbeat.worker_id,
                    heartbeat.attempt,
                )
                return self._document(row)
            self._require_owner(row, heartbeat.worker_id, heartbeat.attempt)
            self._touch_worker_locked(heartbeat.worker_id, now)
            lease_expires_at = min(
                self._deadline(row),
                now + timedelta(seconds=self.lease_seconds),
            )
            self._connection.execute(
                """
                UPDATE distributed_jobs
                SET lease_expires_at = ?, progress_json = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    self._timestamp(lease_expires_at),
                    (
                        self._json(heartbeat.progress.model_dump(mode="json"))
                        if heartbeat.progress is not None
                        else row["progress_json"]
                    ),
                    self._timestamp(now),
                    job_id,
                ),
            )
            return self._document(self._select_required_locked(job_id))

    def complete(
        self,
        job_id: str,
        payload: dict[str, Any],
    ) -> DistributedJobDocument:
        """Accept one verified terminal result from the owning worker attempt."""
        completion = DistributedJobCompletion.model_validate(payload)
        now = self._now()
        with self._lock, self._connection:
            self._recover_locked(now)
            row = self._select_required_locked(job_id)
            current = DistributedJobStatus(row["status"])
            result: dict[str, Any] | None = None
            error: dict[str, Any] | None = None
            result_sha256: str | None = None
            if completion.status == DistributedJobStatus.SUCCEEDED:
                assert completion.result is not None
                result = self._validate_result(row["type"], completion.result)
                result_sha256 = self._digest(result)
            else:
                assert completion.error is not None
                error = completion.error.model_dump(mode="json")

            if current in {
                DistributedJobStatus.SUCCEEDED,
                DistributedJobStatus.FAILED,
            }:
                if self._same_completion(row, completion.status, result, error):
                    return self._document(row)
                raise DistributedJobConflictError("job already has a different result")

            self._require_owner(row, completion.worker_id, completion.attempt)
            self._connection.execute(
                """
                UPDATE distributed_jobs
                SET status = ?, finished_at = ?, result_json = ?,
                    result_sha256 = ?, error_json = ?, lease_expires_at = NULL,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (
                    completion.status.value,
                    self._timestamp(now),
                    self._json(result) if result is not None else None,
                    result_sha256,
                    self._json(error) if error is not None else None,
                    self._timestamp(now),
                    job_id,
                ),
            )
            self._event_locked(
                job_id,
                DistributedJobStatus.RUNNING,
                completion.status,
                now,
                f"completed by {completion.worker_id}",
            )
            LOGGER.info("Distributed job %s completed: %s", job_id, completion.status)
            return self._document(self._select_required_locked(job_id))

    def _initialize(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS distributed_jobs (
                    job_id TEXT PRIMARY KEY,
                    protocol_version INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    timeout_seconds INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    result_json TEXT,
                    result_sha256 TEXT,
                    error_json TEXT,
                    worker_id TEXT,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    lease_expires_at TEXT,
                    request_sha256 TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    progress_json TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in self._connection.execute(
                    "PRAGMA table_info(distributed_jobs)"
                ).fetchall()
            }
            if "progress_json" not in columns:
                self._connection.execute(
                    "ALTER TABLE distributed_jobs ADD COLUMN progress_json TEXT"
                )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_distributed_jobs_dispatch
                ON distributed_jobs(status, created_at)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_distributed_jobs_lease
                ON distributed_jobs(status, lease_expires_at)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS distributed_job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    previous_status TEXT,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES distributed_jobs(job_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS distributed_workers (
                    worker_id TEXT PRIMARY KEY,
                    protocol_version INTEGER NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    worker_version TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    woken_by_ohana INTEGER NOT NULL DEFAULT 0,
                    wake_requested_at TEXT,
                    wake_deadline_at TEXT
                )
                """
            )
            worker_columns = {
                row["name"]
                for row in self._connection.execute(
                    "PRAGMA table_info(distributed_workers)"
                ).fetchall()
            }
            if "woken_by_ohana" not in worker_columns:
                self._connection.execute(
                    "ALTER TABLE distributed_workers "
                    "ADD COLUMN woken_by_ohana INTEGER NOT NULL DEFAULT 0"
                )
            if "wake_requested_at" not in worker_columns:
                self._connection.execute(
                    "ALTER TABLE distributed_workers ADD COLUMN wake_requested_at TEXT"
                )
            if "wake_deadline_at" not in worker_columns:
                self._connection.execute(
                    "ALTER TABLE distributed_workers ADD COLUMN wake_deadline_at TEXT"
                )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS distributed_worker_pairings (
                    pairing_id TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    protocol_version INTEGER NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    worker_version TEXT NOT NULL,
                    polling_secret_sha256 TEXT NOT NULL,
                    verification_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    approved_at TEXT,
                    consumed_at TEXT
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_worker_pairings_status
                ON distributed_worker_pairings(status, expires_at)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS distributed_worker_credentials (
                    worker_id TEXT PRIMARY KEY,
                    token_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                )
                """
            )

    def _recover_locked(self, now: datetime) -> None:
        rows = self._connection.execute(
            """
            SELECT * FROM distributed_jobs
            WHERE status IN (?, ?, ?)
            """,
            (
                DistributedJobStatus.QUEUED.value,
                DistributedJobStatus.WAITING_WORKER.value,
                DistributedJobStatus.RUNNING.value,
            ),
        ).fetchall()
        for row in rows:
            current = DistributedJobStatus(row["status"])
            if self._deadline(row) <= now:
                self._transition_locked(
                    row,
                    DistributedJobStatus.TIMEOUT,
                    now,
                    detail="job timeout elapsed",
                    finished_at=now,
                    clear_lease=True,
                )
                continue
            if (
                current == DistributedJobStatus.RUNNING
                and row["lease_expires_at"] is not None
                and self._parse_timestamp(row["lease_expires_at"]) <= now
            ):
                self._transition_locked(
                    row,
                    DistributedJobStatus.QUEUED,
                    now,
                    detail="worker lease expired; queued for retry",
                    clear_lease=True,
                    clear_owner=True,
                )
                continue
            if (
                current == DistributedJobStatus.QUEUED
                and self._parse_timestamp(row["created_at"])
                + timedelta(seconds=self.waiting_worker_after_seconds)
                <= now
            ):
                self._transition_locked(
                    row,
                    DistributedJobStatus.WAITING_WORKER,
                    now,
                    detail="no compatible worker has claimed the job",
                )
        self._purge_locked(now)

    def _purge_locked(self, now: datetime) -> None:
        cutoff = now - timedelta(days=self.retention_days)
        expired = self._connection.execute(
            """
            SELECT job_id FROM distributed_jobs
            WHERE status IN (?, ?, ?, ?)
              AND finished_at IS NOT NULL
              AND finished_at < ?
            """,
            (
                *(status.value for status in TERMINAL_STATUSES),
                self._timestamp(cutoff),
            ),
        ).fetchall()
        if not expired:
            return
        identifiers = [row["job_id"] for row in expired]
        placeholders = ",".join("?" for _ in identifiers)
        self._connection.execute(
            f"DELETE FROM distributed_job_events WHERE job_id IN ({placeholders})",  # noqa: S608
            identifiers,
        )
        self._connection.execute(
            f"DELETE FROM distributed_jobs WHERE job_id IN ({placeholders})",  # noqa: S608
            identifiers,
        )
        LOGGER.info("Purged %s expired distributed jobs", len(identifiers))

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

    def _transition_locked(
        self,
        row: sqlite3.Row,
        status: DistributedJobStatus,
        now: datetime,
        *,
        detail: str,
        finished_at: datetime | None = None,
        clear_lease: bool = False,
        clear_owner: bool = False,
    ) -> None:
        self._connection.execute(
            """
            UPDATE distributed_jobs
            SET status = ?, finished_at = COALESCE(?, finished_at),
                worker_id = CASE WHEN ? THEN NULL ELSE worker_id END,
                lease_expires_at = CASE WHEN ? THEN NULL ELSE lease_expires_at END,
                updated_at = ?
            WHERE job_id = ?
            """,
            (
                status.value,
                self._timestamp(finished_at) if finished_at else None,
                clear_owner,
                clear_lease,
                self._timestamp(now),
                row["job_id"],
            ),
        )
        previous = DistributedJobStatus(row["status"])
        self._event_locked(row["job_id"], previous, status, now, detail)
        LOGGER.info(
            "Distributed job %s transitioned %s -> %s (%s)",
            row["job_id"],
            previous,
            status,
            detail,
        )

    def _event_locked(
        self,
        job_id: str,
        previous: DistributedJobStatus | None,
        status: DistributedJobStatus,
        now: datetime,
        detail: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO distributed_job_events (
                job_id, occurred_at, previous_status, status, detail
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                job_id,
                self._timestamp(now),
                previous.value if previous else None,
                status.value,
                detail,
            ),
        )

    def _require_owner(self, row: sqlite3.Row, worker_id: str, attempt: int) -> None:
        status = DistributedJobStatus(row["status"])
        if status != DistributedJobStatus.RUNNING:
            raise DistributedJobConflictError(
                f"job is not running (current status: {status.value})"
            )
        self._require_attempt_owner(row, worker_id, attempt)

    @staticmethod
    def _require_attempt_owner(row: sqlite3.Row, worker_id: str, attempt: int) -> None:
        if row["worker_id"] != worker_id or int(row["attempt"]) != attempt:
            raise DistributedJobConflictError("worker does not own this job attempt")

    def _touch_worker_locked(self, worker_id: str, now: datetime) -> None:
        self._connection.execute(
            "UPDATE distributed_workers SET last_seen_at = ? WHERE worker_id = ?",
            (self._timestamp(now), worker_id),
        )

    def _worker_document(
        self, row: sqlite3.Row, now: datetime
    ) -> DistributedWorkerDocument:
        last_seen = self._parse_timestamp(row["last_seen_at"])
        wake_deadline = (
            self._parse_timestamp(row["wake_deadline_at"])
            if row["wake_deadline_at"]
            else None
        )
        if last_seen + timedelta(seconds=self.worker_available_seconds) >= now:
            availability = DistributedWorkerAvailability.AVAILABLE
        elif wake_deadline is not None and wake_deadline >= now:
            availability = DistributedWorkerAvailability.WAKING
        else:
            availability = DistributedWorkerAvailability.UNAVAILABLE
        return DistributedWorkerDocument(
            protocol_version=row["protocol_version"],
            worker_id=row["worker_id"],
            capabilities=json.loads(row["capabilities_json"]),
            platform=row["platform"],
            worker_version=row["worker_version"],
            registered_at=self._parse_timestamp(row["registered_at"]),
            last_seen_at=last_seen,
            availability=availability,
            woken_by_ohana=bool(row["woken_by_ohana"]),
            wake_requested_at=(
                self._parse_timestamp(row["wake_requested_at"])
                if row["wake_requested_at"]
                else None
            ),
            wake_deadline_at=wake_deadline,
        )

    @staticmethod
    def _validate_parameters(job_type: str, value: dict[str, Any]) -> dict[str, Any]:
        models = JOB_TYPE_MODELS.get(job_type)
        if models is None:
            raise ValueError(f"unsupported distributed job type: {job_type}")
        return models[0].model_validate(value).model_dump(mode="json")

    @staticmethod
    def _validate_result(job_type: str, value: dict[str, Any]) -> dict[str, Any]:
        models = JOB_TYPE_MODELS.get(job_type)
        if models is None:
            raise ValueError(f"unsupported distributed job type: {job_type}")
        return models[1].model_validate(value).model_dump(mode="json")

    @staticmethod
    def _same_completion(
        row: sqlite3.Row,
        status: DistributedJobStatus,
        result: dict[str, Any] | None,
        error: dict[str, Any] | None,
    ) -> bool:
        stored_result = json.loads(row["result_json"]) if row["result_json"] else None
        stored_error = json.loads(row["error_json"]) if row["error_json"] else None
        return (
            row["status"] == status.value
            and stored_result == result
            and stored_error == error
        )

    def _select_required_locked(self, job_id: str) -> sqlite3.Row:
        row = self._select_locked(job_id)
        if row is None:
            raise LookupError(f"distributed job not found: {job_id}")
        return row

    def _select_locked(self, job_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM distributed_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()

    def _document(self, row: sqlite3.Row) -> DistributedJobDocument:
        return DistributedJobDocument(
            protocol_version=row["protocol_version"],
            job_id=row["job_id"],
            type=row["type"],
            created_at=self._parse_timestamp(row["created_at"]),
            parameters=json.loads(row["parameters_json"]),
            timeout=row["timeout_seconds"],
            status=row["status"],
            started_at=(
                self._parse_timestamp(row["started_at"]) if row["started_at"] else None
            ),
            finished_at=(
                self._parse_timestamp(row["finished_at"])
                if row["finished_at"]
                else None
            ),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            result_sha256=row["result_sha256"],
            error=json.loads(row["error_json"]) if row["error_json"] else None,
            worker_id=row["worker_id"],
            attempt=row["attempt"],
            lease_expires_at=(
                self._parse_timestamp(row["lease_expires_at"])
                if row["lease_expires_at"]
                else None
            ),
            progress=(
                json.loads(row["progress_json"]) if row["progress_json"] else None
            ),
        )

    def _deadline(self, row: sqlite3.Row) -> datetime:
        return self._parse_timestamp(row["created_at"]) + timedelta(
            seconds=int(row["timeout_seconds"])
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("distributed job clock must return a timezone-aware value")
        return value.astimezone(UTC)

    @staticmethod
    def _timestamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _digest(cls, value: object) -> str:
        return hashlib.sha256(cls._json(value).encode("utf-8")).hexdigest()
