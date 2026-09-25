"""Katsuyu worker registration, capabilities, availability and wake state."""

from __future__ import annotations

import hmac
import json
import logging
import sqlite3
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Any

from ohana_agent.contracts.administration import (
    DistributedJobStatus,
    DistributedWorkerAvailability,
    DistributedWorkerCollection,
    DistributedWorkerDocument,
    DistributedWorkerRegistration,
)
from ohana_agent.jobs.job_types import (
    JOB_TYPE_MODELS,
    DistributedJobConflictError,
)

LOGGER = logging.getLogger(__name__)


class DistributedWorkerRegistry:
    """Katsuyu worker registration, capabilities, availability and wake state."""

    def register_worker(
        self,
        payload: dict[str, Any],
        *,
        previous_worker_id: str | None = None,
    ) -> DistributedWorkerDocument:
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
            if previous_worker_id and previous_worker_id != normalized.worker_id:
                self._migrate_worker_identity_locked(
                    previous_worker_id,
                    normalized.worker_id,
                )
            existing = self._connection.execute(
                "SELECT * FROM distributed_workers WHERE worker_id = ?",
                (normalized.worker_id,),
            ).fetchone()
            if (
                normalized.wake_on_lan_mac_address is None
                and existing is not None
                and existing["wake_on_lan_mac_address"]
            ):
                normalized = normalized.model_copy(
                    update={
                        "wake_on_lan_mac_address": existing["wake_on_lan_mac_address"]
                    }
                )
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
                    wake_requested_at, wake_deadline_at, wake_on_lan_mac_address
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    protocol_version = excluded.protocol_version,
                    capabilities_json = excluded.capabilities_json,
                    platform = excluded.platform,
                    worker_version = excluded.worker_version,
                    last_seen_at = excluded.last_seen_at,
                    woken_by_ohana = excluded.woken_by_ohana,
                    wake_requested_at = excluded.wake_requested_at,
                    wake_deadline_at = excluded.wake_deadline_at,
                    wake_on_lan_mac_address = excluded.wake_on_lan_mac_address
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
                    normalized.wake_on_lan_mac_address,
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

    def wake_candidate(
        self,
        job_type: str,
        *,
        minimum_interval_seconds: int = 0,
        fallback_worker_id: str | None = None,
        fallback_mac_address: str | None = None,
    ) -> DistributedWorkerDocument | None:
        """Return one unavailable compatible worker with an effective WOL MAC."""
        if minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        now = self._now()
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM distributed_workers "
                "ORDER BY julianday(last_seen_at) DESC"
            ).fetchall()
        compatible = [
            self._worker_document(row, now)
            for row in rows
            if job_type in json.loads(row["capabilities_json"])
        ]
        if any(
            worker.availability
            in {
                DistributedWorkerAvailability.AVAILABLE,
                DistributedWorkerAvailability.WAKING,
            }
            for worker in compatible
        ):
            return None
        if minimum_interval_seconds > 0 and any(
            worker.wake_requested_at is not None
            and worker.wake_requested_at + timedelta(seconds=minimum_interval_seconds)
            > now
            for worker in compatible
        ):
            return None
        advertised = next(
            (
                worker
                for worker in compatible
                if worker.wake_on_lan_mac_address is not None
            ),
            None,
        )
        if advertised is not None:
            return advertised
        if fallback_worker_id is None or fallback_mac_address is None:
            return None
        configured = next(
            (worker for worker in compatible if worker.worker_id == fallback_worker_id),
            None,
        )
        if configured is None:
            return None
        return configured.model_copy(
            update={"wake_on_lan_mac_address": fallback_mac_address}
        )

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

    def has_worker_capability(self, job_type: str) -> bool:
        """Return whether a previously authenticated worker declared this type."""
        if job_type not in JOB_TYPE_MODELS:
            return False
        with self._lock:
            rows = self._connection.execute(
                "SELECT capabilities_json FROM distributed_workers"
            ).fetchall()
        return any(job_type in json.loads(row["capabilities_json"]) for row in rows)

    def wake_ready_job_types(
        self,
        *,
        batch_window_seconds: int,
        job_types: Collection[str] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> tuple[str, ...]:
        """Return queued job types old enough to justify one grouped WOL."""
        if batch_window_seconds < 0 or batch_window_seconds > 3600:
            raise ValueError("batch_window_seconds must be between 0 and 3600")
        now = self._now()
        ready_at = now - timedelta(seconds=batch_window_seconds)
        allowed_types = tuple(sorted(set(job_types or ())))
        type_filter = ""
        type_parameters: tuple[str, ...] = ()
        date_filter = ""
        date_parameters: tuple[str, ...] = ()
        if created_after is not None:
            date_filter += " AND created_at >= ?"
            date_parameters += (self._timestamp(created_after),)
        if created_before is not None:
            date_filter += " AND created_at <= ?"
            date_parameters += (self._timestamp(created_before),)
        if job_types is not None:
            if not allowed_types:
                return ()
            placeholders = ",".join("?" for _ in allowed_types)
            type_filter = f" AND type IN ({placeholders})"
            type_parameters = allowed_types
        with self._lock, self._connection:
            self._recover_locked(now)
            rows = self._connection.execute(
                f"""
                SELECT type FROM distributed_jobs
                WHERE status IN (?, ?) AND created_at <= ?
                {type_filter}
                {date_filter}
                GROUP BY type
                ORDER BY MIN(created_at) ASC, type ASC
                """,
                (
                    DistributedJobStatus.QUEUED.value,
                    DistributedJobStatus.WAITING_WORKER.value,
                    self._timestamp(ready_at),
                    *type_parameters,
                    *date_parameters,
                ),
            ).fetchall()
        return tuple(row["type"] for row in rows)

    def authorize_worker(
        self,
        worker_id: str,
        token: str,
        *,
        previous_worker_id: str | None = None,
    ) -> bool:
        """Validate a per-worker bearer credential without storing its clear text."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT token_sha256 FROM distributed_worker_credentials
                WHERE worker_id = ? AND revoked_at IS NULL
                """,
                (worker_id,),
            ).fetchone()
            if row is None and previous_worker_id and previous_worker_id != worker_id:
                row = self._connection.execute(
                    """
                    SELECT token_sha256 FROM distributed_worker_credentials
                    WHERE worker_id = ? AND revoked_at IS NULL
                    """,
                    (previous_worker_id,),
                ).fetchone()
        return row is not None and hmac.compare_digest(
            row["token_sha256"], self._secret_digest(token)
        )

    def _idle_shutdown_locked(self, worker_id: str, now: datetime) -> bool:
        """Stop only an Ohana-woken worker after all relevant work has settled."""
        row = self._connection.execute(
            "SELECT * FROM distributed_workers WHERE worker_id=?", (worker_id,)
        ).fetchone()
        if row is None or not self._worker_document(row, now).woken_by_ohana:
            return False
        pending = self._connection.execute(
            """SELECT 1 FROM distributed_jobs
            WHERE (status IN ('QUEUED','WAITING_WORKER','RUNNING')
                   AND (type IN (SELECT value FROM json_each(?)) OR worker_id=?))
               OR completion_processed=0 LIMIT 1""",
            (row["capabilities_json"], worker_id),
        ).fetchone()
        if pending is not None:
            return False
        self._connection.execute(
            """UPDATE distributed_workers SET woken_by_ohana=0,
            wake_requested_at=NULL, wake_deadline_at=NULL WHERE worker_id=?""",
            (worker_id,),
        )
        return True

    def _migrate_worker_identity_locked(
        self,
        previous_worker_id: str,
        worker_id: str,
    ) -> None:
        """Move one paired worker identity without rotating its credential."""
        target_credential = self._connection.execute(
            "SELECT 1 FROM distributed_worker_credentials WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()
        if target_credential is not None:
            raise DistributedJobConflictError(
                f"worker identity already exists: {worker_id}"
            )
        previous_credential = self._connection.execute(
            "SELECT 1 FROM distributed_worker_credentials WHERE worker_id = ?",
            (previous_worker_id,),
        ).fetchone()
        if previous_credential is None:
            raise LookupError(f"distributed worker not found: {previous_worker_id}")

        target_worker = self._connection.execute(
            "SELECT 1 FROM distributed_workers WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()
        if target_worker is not None:
            raise DistributedJobConflictError(
                f"worker identity already exists: {worker_id}"
            )

        self._connection.execute(
            "UPDATE distributed_worker_credentials "
            "SET worker_id = ? WHERE worker_id = ?",
            (worker_id, previous_worker_id),
        )
        self._connection.execute(
            "UPDATE distributed_workers SET worker_id = ? WHERE worker_id = ?",
            (worker_id, previous_worker_id),
        )
        self._connection.execute(
            "UPDATE distributed_worker_pairings SET worker_id = ? WHERE worker_id = ?",
            (worker_id, previous_worker_id),
        )
        self._connection.execute(
            "UPDATE distributed_jobs SET worker_id = ? WHERE worker_id = ?",
            (worker_id, previous_worker_id),
        )
        LOGGER.info(
            "Katsuyu worker identity migrated %s -> %s",
            previous_worker_id,
            worker_id,
        )

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
            wake_on_lan_mac_address=row["wake_on_lan_mac_address"],
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

    def _should_shutdown_after_claim_locked(
        self,
        worker_id: str,
        job_id: str,
        compatible_types: list[str],
        now: datetime,
    ) -> bool:
        worker_row = self._connection.execute(
            "SELECT * FROM distributed_workers WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()
        if worker_row is None:
            return False
        worker = self._worker_document(worker_row, now)
        if not worker.woken_by_ohana:
            return False

        placeholders = ",".join("?" for _ in compatible_types)
        queued = self._connection.execute(
            f"""
            SELECT 1 FROM distributed_jobs
            WHERE job_id != ?
              AND status IN (?, ?)
              AND type IN ({placeholders})
            LIMIT 1
            """,  # noqa: S608 - placeholders are generated, values remain bound.
            (
                job_id,
                DistributedJobStatus.QUEUED.value,
                DistributedJobStatus.WAITING_WORKER.value,
                *compatible_types,
            ),
        ).fetchone()
        return queued is None
