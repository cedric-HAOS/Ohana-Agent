"""Durable, leased and explicitly typed jobs coordinated by Ohana-Agent."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from ohana_agent.contracts.administration import (
    DistributedJobClaim,
    DistributedJobClaimResult,
    DistributedJobCompletion,
    DistributedJobCreate,
    DistributedJobDocument,
    DistributedJobHeartbeat,
    DistributedJobPollResult,
    DistributedJobStatus,
)
from ohana_agent.jobs.job_types import (
    AUTOMATIC_WAKE_JOB_TYPES,
    JOB_TYPE_MODELS,
    LOCAL_TIMEZONE,
    TERMINAL_STATUSES,
    DistributedJobConflictError,
)
from ohana_agent.jobs.pairings import DistributedWorkerPairings
from ohana_agent.jobs.schema import DistributedJobSchema
from ohana_agent.jobs.workers import DistributedWorkerRegistry

LOGGER = logging.getLogger(__name__)


class DistributedJobRepository(
    DistributedJobSchema, DistributedWorkerPairings, DistributedWorkerRegistry
):
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
        self._clock = clock or (lambda: datetime.now(LOCAL_TIMEZONE))
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

    def now(self) -> datetime:
        """Return the repository clock used for deterministic coordination."""
        return self._now()

    def create(self, payload: dict[str, Any]) -> DistributedJobDocument:
        """Validate and durably enqueue one idempotent Tsunade request."""
        request = DistributedJobCreate.model_validate(payload)
        parameters = self._validate_parameters(request.type, request.parameters)
        now = self._now()
        timeout = request.timeout
        if request.type in AUTOMATIC_WAKE_JOB_TYPES and now.hour < 5:
            batch_end = now.replace(hour=5, minute=0, second=0, microsecond=0)
            timeout = max(timeout, int((batch_end - now).total_seconds()) + 1)
        normalized = request.model_copy(
            update={"parameters": parameters, "timeout": timeout}
        )
        request_sha256 = self._digest(normalized.model_dump(mode="json"))
        created_at = request.created_at
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
                timeout,
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

    def latest_successful_result(self, job_type: str) -> dict[str, Any] | None:
        """Return one compact validated result for deterministic comparison."""
        if job_type not in JOB_TYPE_MODELS:
            raise ValueError(f"unsupported distributed job type: {job_type}")
        with self._lock:
            row = self._connection.execute(
                """SELECT result_json FROM distributed_jobs
                WHERE type = ? AND status = ? AND result_json IS NOT NULL
                ORDER BY finished_at DESC LIMIT 1""",
                (job_type, DistributedJobStatus.SUCCEEDED.value),
            ).fetchone()
        return json.loads(row["result_json"]) if row is not None else None

    def latest_log_health_sources(
        self, sources: list[str], *, window_seconds: int | None = None
    ) -> list[dict[str, Any]]:
        """Use a complete collection of matching elapsed duration when requested."""
        results: list[dict[str, Any]] = []
        with self._lock:
            for source in dict.fromkeys(sources):
                row = self._connection.execute(
                    """SELECT source.value AS source_json
                    FROM distributed_jobs AS job,
                         json_each(job.result_json, '$.sources') AS source
                    WHERE job.type = 'logs.health_check' AND job.status = ?
                      AND json_extract(source.value, '$.source') = ?
                      AND json_type(source.value, '$.truncated') = 'false'
                      AND (? IS NULL OR ROUND((
                        julianday(json_extract(job.result_json, '$.window_ended_at'))
                        - julianday(json_extract(
                            job.result_json, '$.window_started_at'))
                      ) * 86400) = ?)
                    ORDER BY julianday(job.finished_at) DESC, job.job_id DESC
                    LIMIT 1""",
                    (
                        DistributedJobStatus.SUCCEEDED.value,
                        source,
                        window_seconds,
                        window_seconds,
                    ),
                ).fetchone()
                if row is not None:
                    results.append(json.loads(row["source_json"]))
        return results

    def latest(self, job_type: str) -> DistributedJobDocument | None:
        """Return the latest bounded job document for one declared type."""
        if job_type not in JOB_TYPE_MODELS:
            raise ValueError(f"unsupported distributed job type: {job_type}")
        with self._lock, self._connection:
            self._recover_locked(self._now())
            row = self._connection.execute(
                """SELECT * FROM distributed_jobs WHERE type = ?
                ORDER BY julianday(created_at) DESC, job_id DESC LIMIT 1""",
                (job_type,),
            ).fetchone()
        return self._document(row) if row is not None else None

    def latest_for_incident(
        self, job_type: str, incident_id: str | None
    ) -> DistributedJobDocument | None:
        """Return the latest job whose bounded parameters target one incident."""
        if job_type not in JOB_TYPE_MODELS:
            raise ValueError(f"unsupported distributed job type: {job_type}")
        with self._lock, self._connection:
            self._recover_locked(self._now())
            rows = self._connection.execute(
                """SELECT * FROM distributed_jobs WHERE type = ?
                ORDER BY julianday(created_at) DESC, job_id DESC LIMIT 100""",
                (job_type,),
            ).fetchall()
        for row in rows:
            parameters = json.loads(row["parameters_json"])
            if parameters.get("incident_id") == incident_id:
                return self._document(row)
        return None

    def count(self, job_type: str) -> int:
        """Count durable jobs of one declared type without loading their payloads."""
        if job_type not in JOB_TYPE_MODELS:
            raise ValueError(f"unsupported distributed job type: {job_type}")
        with self._lock:
            return int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM distributed_jobs WHERE type = ?",
                    (job_type,),
                ).fetchone()[0]
            )

    def active_for_incident(
        self, job_type: str, incident_id: str | None
    ) -> DistributedJobDocument | None:
        """Return an equivalent active control-plane job, if one exists."""
        if job_type not in JOB_TYPE_MODELS:
            raise ValueError(f"unsupported distributed job type: {job_type}")
        with self._lock, self._connection:
            self._recover_locked(self._now())
            rows = self._connection.execute(
                """SELECT * FROM distributed_jobs
                WHERE type = ? AND status NOT IN (?, ?, ?, ?)
                ORDER BY julianday(created_at) ASC""",
                (
                    job_type,
                    *(status.value for status in TERMINAL_STATUSES),
                ),
            ).fetchall()
            for row in rows:
                parameters = json.loads(row["parameters_json"])
                if parameters.get("incident_id") == incident_id:
                    return self._document(row)
        return None

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

    def claim(
        self,
        payload: dict[str, Any],
        *,
        shutdown_after_completion: bool = True,
        settle: bool = False,
    ) -> DistributedJobClaimResult:
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
                ORDER BY julianday(created_at) ASC, job_id ASC
                LIMIT 1
                """,  # noqa: S608 - placeholders are generated, values remain bound.
                (
                    DistributedJobStatus.QUEUED.value,
                    DistributedJobStatus.WAITING_WORKER.value,
                    *compatible_types,
                ),
            ).fetchone()
            if row is None:
                if settle:
                    shutdown = shutdown_after_completion and self._idle_shutdown_locked(
                        claim.worker_id, now
                    )
                    return DistributedJobPollResult(shutdown_requested=shutdown)
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
            should_shutdown = (
                self._should_shutdown_after_claim_locked(
                    claim.worker_id,
                    row["job_id"],
                    compatible_types,
                    now,
                )
                if shutdown_after_completion and not settle
                else False
            )
            document = self._document(
                self._select_required_locked(row["job_id"]),
                shutdown_after_completion=should_shutdown,
            )
            if settle:
                return DistributedJobPollResult(job=document)
            return DistributedJobClaimResult(job=document)

    def pending_completions(
        self, *, failures_only: bool = False
    ) -> list[DistributedJobDocument]:
        """Resume durable result processing before considering a worker idle."""
        with self._lock, self._connection:
            self._recover_locked(self._now())
            rows = self._connection.execute(
                """SELECT * FROM distributed_jobs WHERE completion_processed=0
                AND (?=0 OR status IN ('FAILED','TIMEOUT','CANCELLED'))
                ORDER BY julianday(finished_at), job_id LIMIT 16""",
                (int(failures_only),),
            ).fetchall()
            return [self._document(row) for row in rows]

    def mark_completion_processed(self, job_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE distributed_jobs SET completion_processed=1 WHERE job_id=?",
                (job_id,),
            )

    def authorize_job_transfer(
        self,
        job_id: str,
        *,
        worker_id: str,
        attempt: int,
        job_type: str | tuple[str, ...] = "backup.infra",
    ) -> DistributedJobDocument:
        """Authorize a bounded transfer for the worker owning a running job."""
        now = self._now()
        with self._lock, self._connection:
            self._recover_locked(now)
            row = self._select_required_locked(job_id)
            self._require_owner(row, worker_id, attempt)
            permitted_types = (job_type,) if isinstance(job_type, str) else job_type
            if row["type"] not in permitted_types:
                raise DistributedJobConflictError(
                    f"job type does not permit this transfer: {row['type']}"
                )
            self._touch_worker_locked(worker_id, now)
            return self._document(row)

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
            if row["type"] in {"logs.health_check", "logs.investigate", "ai.inference"}:
                self._connection.execute(
                    "UPDATE distributed_jobs SET completion_processed=0 WHERE job_id=?",
                    (job_id,),
                )
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
        if status in TERMINAL_STATUSES and row["type"] in {
            "ai.inference",
            "logs.investigate",
        }:
            self._connection.execute(
                "UPDATE distributed_jobs SET completion_processed=0 WHERE job_id=?",
                (row["job_id"],),
            )
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

    def _document(
        self,
        row: sqlite3.Row,
        *,
        shutdown_after_completion: bool = False,
    ) -> DistributedJobDocument:
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
            shutdown_after_completion=shutdown_after_completion,
        )

    def _deadline(self, row: sqlite3.Row) -> datetime:
        return self._parse_timestamp(row["created_at"]) + timedelta(
            seconds=int(row["timeout_seconds"])
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("distributed job clock must return a timezone-aware value")
        return value.astimezone(LOCAL_TIMEZONE)

    @staticmethod
    def _timestamp(value: datetime) -> str:
        return value.astimezone(LOCAL_TIMEZONE).isoformat()

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

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
