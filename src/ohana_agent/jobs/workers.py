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
    DistributedWorkerCapabilityActivity,
    DistributedWorkerCollection,
    DistributedWorkerDocument,
    DistributedWorkerHost,
    DistributedWorkerPowerEvent,
    DistributedWorkerPowerEventKind,
    DistributedWorkerPowerReport,
    DistributedWorkerRegistration,
    DistributedWorkerRuntime,
    DistributedWorkerRuntimeReport,
    DistributedWorkerStatusDocument,
    DistributedWorkerWakeStats,
)
from ohana_agent.jobs.job_types import (
    JOB_TYPE_MODELS,
    DistributedJobConflictError,
)

LOGGER = logging.getLogger(__name__)

LATE_ANSWER_SECONDS = 1800
POWER_EVENT_RETENTION = 200
POWER_EVENTS_SHOWN = 30


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
            requested = wake_requested_at or (
                existing["wake_requested_at"] if existing else None
            )
            if requested:
                self._record_worker_online_locked(
                    normalized.worker_id,
                    self._parse_timestamp(requested),
                    now,
                    expired=bool(
                        existing
                        and existing["wake_deadline_at"]
                        and self._parse_timestamp(existing["wake_deadline_at"]) < now
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

    def report_worker_runtimes(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Store the local runtime state Katsuyu checked for its capabilities.

        Separate from registration: re-registering would end an Ohana wake.
        """
        report = DistributedWorkerRuntimeReport.model_validate(payload)
        now = self._now()
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT capabilities_json FROM distributed_workers WHERE worker_id = ?",
                (report.worker_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"distributed worker not found: {report.worker_id}")
            capabilities = set(json.loads(row["capabilities_json"]))
            runtimes = {
                capability: runtime.model_dump(mode="json")
                for capability, runtime in sorted(report.runtimes.items())
                if capability in capabilities
            }
            self._connection.execute(
                """
                UPDATE distributed_workers
                SET runtimes_json = ?, runtimes_reported_at = ?, last_seen_at = ?,
                    host_json = COALESCE(?, host_json)
                WHERE worker_id = ?
                """,
                (
                    self._json(runtimes),
                    self._timestamp(now),
                    self._timestamp(now),
                    (
                        self._json(report.host.model_dump(mode="json"))
                        if report.host is not None
                        else None
                    ),
                    report.worker_id,
                ),
            )
        LOGGER.info(
            "Katsuyu worker %s runtimes: %s",
            report.worker_id,
            ", ".join(f"{key}={value['state']}" for key, value in runtimes.items())
            or "none",
        )
        return {
            "protocol_version": 1,
            "worker_id": report.worker_id,
            "runtimes": runtimes,
            "reported_at": now.isoformat(),
        }

    def list_workers(self) -> DistributedWorkerCollection:
        """Return the latest authenticated registrations to Tsunade."""
        self.settle_unanswered_wakes()
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM distributed_workers ORDER BY worker_id"
            ).fetchall()
            activity = {row["worker_id"]: self._activity_locked(row) for row in rows}
            power_events = {
                row["worker_id"]: self._power_events_locked(row["worker_id"])
                for row in rows
            }
            wake_stats = {
                row["worker_id"]: self._wake_stats_locked(row["worker_id"])
                for row in rows
            }
        now = self._now()
        return DistributedWorkerCollection(
            workers=[
                DistributedWorkerStatusDocument(
                    **self._worker_document(row, now).model_dump(),
                    runtimes={
                        capability: DistributedWorkerRuntime.model_validate(runtime)
                        for capability, runtime in json.loads(
                            row["runtimes_json"] or "{}"
                        ).items()
                    },
                    runtimes_reported_at=(
                        self._parse_timestamp(row["runtimes_reported_at"])
                        if row["runtimes_reported_at"]
                        else None
                    ),
                    activity=activity[row["worker_id"]],
                    power_events=power_events[row["worker_id"]],
                    wake_stats=wake_stats[row["worker_id"]],
                    host=(
                        DistributedWorkerHost.model_validate_json(row["host_json"])
                        if row["host_json"]
                        else None
                    ),
                )
                for row in rows
            ]
        )

    def _activity_locked(
        self, worker: sqlite3.Row
    ) -> list[DistributedWorkerCapabilityActivity]:
        """Last success and failure per announced capability, from retained jobs."""
        rows = self._connection.execute(
            """
            SELECT type, status, finished_at, error_json FROM (
                SELECT type, status, finished_at, error_json,
                    ROW_NUMBER() OVER (
                        PARTITION BY type, status = ?
                        ORDER BY julianday(finished_at) DESC
                    ) AS rank
                FROM distributed_jobs
                WHERE worker_id = ? AND finished_at IS NOT NULL
                  AND status IN (?, ?, ?)
            ) WHERE rank = 1
            """,
            (
                DistributedJobStatus.SUCCEEDED.value,
                worker["worker_id"],
                DistributedJobStatus.SUCCEEDED.value,
                DistributedJobStatus.FAILED.value,
                DistributedJobStatus.TIMEOUT.value,
            ),
        ).fetchall()
        activity = {
            capability: DistributedWorkerCapabilityActivity(type=capability)
            for capability in json.loads(worker["capabilities_json"])
        }
        for row in rows:
            current = activity.setdefault(
                row["type"], DistributedWorkerCapabilityActivity(type=row["type"])
            )
            finished_at = self._parse_timestamp(row["finished_at"])
            if row["status"] == DistributedJobStatus.SUCCEEDED.value:
                current.last_succeeded_at = finished_at
                continue
            error = json.loads(row["error_json"]) if row["error_json"] else {}
            current.last_failed_at = finished_at
            current.last_failure_status = DistributedJobStatus(row["status"])
            message = error.get("message") if isinstance(error, dict) else None
            current.last_failure_message = (
                str(message)[:300] if message is not None else None
            )
        return [activity[capability] for capability in sorted(activity)]

    def mark_worker_waking(
        self,
        worker_id: str,
        *,
        timeout_seconds: int,
        trigger: str = "manual",
    ) -> DistributedWorkerDocument:
        """Persist that Ohana sent WOL for a known, currently unavailable worker.

        ``trigger`` is why Ohana woke it: ``queued_jobs`` (work was waiting),
        ``retry`` (an earlier wake got no answer) or ``manual`` (an explicit
        test from Vision).
        """
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
            self._power_event_locked(
                worker_id,
                DistributedWorkerPowerEventKind.WAKE_SENT,
                now,
                {
                    "trigger": trigger,
                    "attempt": self._unanswered_wakes_locked(worker_id) + 1,
                    "pending_jobs": self._pending_jobs_locked(row),
                    "timeout_seconds": timeout_seconds,
                },
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
        self._power_event_locked(
            worker_id,
            DistributedWorkerPowerEventKind.SHUTDOWN_GRANTED,
            now,
            self._executed_since_locked(row),
        )
        self._connection.execute(
            """UPDATE distributed_workers SET woken_by_ohana=0,
            wake_requested_at=NULL, wake_deadline_at=NULL WHERE worker_id=?""",
            (worker_id,),
        )
        return True

    def report_worker_power(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record what Katsuyu did with the shutdown Agent granted it."""
        report = DistributedWorkerPowerReport.model_validate(payload)
        now = self._now()
        detail: dict[str, Any] = {}
        if report.reason is not None:
            detail["reason"] = report.reason
        if report.sessions is not None:
            detail["sessions"] = report.sessions
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT worker_id FROM distributed_workers WHERE worker_id = ?",
                (report.worker_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"distributed worker not found: {report.worker_id}")
            self._power_event_locked(
                report.worker_id,
                DistributedWorkerPowerEventKind(report.outcome),
                now,
                detail,
            )
        LOGGER.info(
            "Katsuyu worker %s: %s%s",
            report.worker_id,
            report.outcome,
            f" ({report.reason})" if report.reason else "",
        )
        return {
            "protocol_version": 1,
            "worker_id": report.worker_id,
            "outcome": report.outcome,
            "recorded_at": now.isoformat(),
        }

    def settle_unanswered_wakes(self, *, max_attempts: int = 3) -> None:
        """Record the wakes whose wait ran out without the worker connecting.

        After ``max_attempts`` unanswered wakes in a row the cycle is abandoned
        explicitly while work still waits; the jobs then follow their own timeout.
        """
        now = self._now()
        with self._lock, self._connection:
            for row in self._connection.execute(
                "SELECT * FROM distributed_workers WHERE wake_deadline_at IS NOT NULL"
            ).fetchall():
                last = self._connection.execute(
                    """SELECT kind FROM distributed_worker_power_events
                    WHERE worker_id = ? ORDER BY event_id DESC LIMIT 1""",
                    (row["worker_id"],),
                ).fetchone()
                deadline = self._parse_timestamp(row["wake_deadline_at"])
                if (
                    last is None
                    or last["kind"] != DistributedWorkerPowerEventKind.WAKE_SENT
                    or deadline >= now
                    or self._worker_document(row, now).availability
                    == DistributedWorkerAvailability.AVAILABLE
                ):
                    continue
                attempt = self._unanswered_wakes_locked(row["worker_id"]) + 1
                pending = self._pending_jobs_locked(row)
                self._power_event_locked(
                    row["worker_id"],
                    DistributedWorkerPowerEventKind.WAKE_TIMEOUT,
                    deadline,
                    {"attempt": attempt},
                )
                if attempt >= max_attempts and pending:
                    self._power_event_locked(
                        row["worker_id"],
                        DistributedWorkerPowerEventKind.WAKE_ABANDONED,
                        now,
                        {"attempts": attempt, "pending_jobs": pending},
                    )
                LOGGER.warning(
                    "Katsuyu worker %s did not answer wake attempt %s",
                    row["worker_id"],
                    attempt,
                )

    def unanswered_wake_retry(
        self, *, retry_delay_seconds: int, max_attempts: int = 3
    ) -> DistributedWorkerDocument | None:
        """A worker that stayed silent after a wake while work still waits."""
        self.settle_unanswered_wakes(max_attempts=max_attempts)
        now = self._now()
        with self._lock:
            for row in self._connection.execute(
                "SELECT * FROM distributed_workers"
            ).fetchall():
                last = self._connection.execute(
                    """SELECT kind, occurred_at FROM distributed_worker_power_events
                    WHERE worker_id = ? ORDER BY event_id DESC LIMIT 1""",
                    (row["worker_id"],),
                ).fetchone()
                if (
                    last is None
                    or last["kind"] != DistributedWorkerPowerEventKind.WAKE_TIMEOUT
                    or self._parse_timestamp(last["occurred_at"])
                    + timedelta(seconds=retry_delay_seconds)
                    > now
                    or self._unanswered_wakes_locked(row["worker_id"]) >= max_attempts
                    or not self._pending_jobs_locked(row)
                ):
                    continue
                document = self._worker_document(row, now)
                if document.availability == DistributedWorkerAvailability.UNAVAILABLE:
                    return document
        return None

    def _unanswered_wakes_locked(self, worker_id: str) -> int:
        """Wake attempts left unanswered since the last connection or abandonment."""
        rows = self._connection.execute(
            """SELECT kind FROM distributed_worker_power_events
            WHERE worker_id = ? ORDER BY event_id DESC""",
            (worker_id,),
        ).fetchall()
        count = 0
        for row in rows:
            if row["kind"] in {
                DistributedWorkerPowerEventKind.WORKER_ONLINE,
                DistributedWorkerPowerEventKind.WAKE_ABANDONED,
            }:
                break
            if row["kind"] == DistributedWorkerPowerEventKind.WAKE_TIMEOUT:
                count += 1
        return count

    def _wake_stats_locked(self, worker_id: str) -> DistributedWorkerWakeStats:
        rows = self._connection.execute(
            """SELECT occurred_at, kind, detail_json
            FROM distributed_worker_power_events
            WHERE worker_id = ? ORDER BY event_id""",
            (worker_id,),
        ).fetchall()
        stats = DistributedWorkerWakeStats()
        delays: list[int] = []
        timed_out_since_answer = False
        for row in rows:
            kind = row["kind"]
            detail = json.loads(row["detail_json"])
            if stats.since is None:
                stats.since = self._parse_timestamp(row["occurred_at"])
            if kind == DistributedWorkerPowerEventKind.WAKE_SENT:
                stats.attempts += 1
            elif kind == DistributedWorkerPowerEventKind.WAKE_FAILED:
                stats.send_failures += 1
            elif kind == DistributedWorkerPowerEventKind.WAKE_TIMEOUT:
                stats.unanswered += 1
                timed_out_since_answer = True
            elif kind == DistributedWorkerPowerEventKind.WAKE_ABANDONED:
                stats.abandoned += 1
            elif kind == DistributedWorkerPowerEventKind.WORKER_ONLINE:
                answered_after_timeout = timed_out_since_answer
                timed_out_since_answer = False
                if detail.get("manual"):
                    continue
                delays.append(int(detail.get("after_seconds", 0)))
                if detail.get("late"):
                    stats.late += 1
                    # A late answer settles an attempt counted as unanswered.
                    if answered_after_timeout:
                        stats.unanswered -= 1
                else:
                    stats.on_time += 1
        if delays:
            ordered = sorted(delays)
            stats.median_seconds = ordered[len(ordered) // 2]
            stats.max_seconds = ordered[-1]
        return stats

    def record_wake_failure(self, worker_id: str, error: str, *, trigger: str) -> None:
        """Keep a trace of a Wake-on-LAN that could not even be sent."""
        with self._lock, self._connection:
            self._power_event_locked(
                worker_id,
                DistributedWorkerPowerEventKind.WAKE_FAILED,
                self._now(),
                {"trigger": trigger, "error": error[:200]},
            )

    def _pending_jobs_locked(self, worker: sqlite3.Row) -> dict[str, int]:
        """Jobs waiting for this worker's capabilities, per type."""
        rows = self._connection.execute(
            """SELECT type, COUNT(*) AS total FROM distributed_jobs
            WHERE status IN (?, ?) AND type IN (SELECT value FROM json_each(?))
            GROUP BY type ORDER BY type""",
            (
                DistributedJobStatus.QUEUED.value,
                DistributedJobStatus.WAITING_WORKER.value,
                worker["capabilities_json"],
            ),
        ).fetchall()
        return {row["type"]: int(row["total"]) for row in rows}

    def _executed_since_locked(self, worker: sqlite3.Row) -> dict[str, Any]:
        """What the worker ran since Ohana woke it (its whole cycle)."""
        if not worker["wake_requested_at"]:
            return {"executed": {}, "failed": 0}
        rows = self._connection.execute(
            """SELECT type, status, COUNT(*) AS total FROM distributed_jobs
            WHERE worker_id = ? AND started_at IS NOT NULL
              AND julianday(started_at) >= julianday(?)
            GROUP BY type, status ORDER BY type""",
            (worker["worker_id"], worker["wake_requested_at"]),
        ).fetchall()
        executed: dict[str, int] = {}
        failed = 0
        for row in rows:
            executed[row["type"]] = executed.get(row["type"], 0) + int(row["total"])
            if row["status"] in {
                DistributedJobStatus.FAILED.value,
                DistributedJobStatus.TIMEOUT.value,
            }:
                failed += int(row["total"])
        return {"executed": executed, "failed": failed}

    def _record_worker_online_locked(
        self,
        worker_id: str,
        requested_at: datetime,
        now: datetime,
        *,
        expired: bool = False,
    ) -> None:
        """Note the first registration after a wake (later ones are restarts).

        A registration after the wait ran out is a late answer: it is kept, but
        Ohana no longer owns the cycle, so the PC is not stopped afterwards.
        """
        last = self._connection.execute(
            """SELECT kind FROM distributed_worker_power_events
            WHERE worker_id = ? ORDER BY event_id DESC LIMIT 1""",
            (worker_id,),
        ).fetchone()
        if last is None or last["kind"] not in {
            DistributedWorkerPowerEventKind.WAKE_SENT,
            DistributedWorkerPowerEventKind.WAKE_TIMEOUT,
            DistributedWorkerPowerEventKind.WAKE_ABANDONED,
        }:
            return
        elapsed = max(0, round((now - requested_at).total_seconds()))
        detail: dict[str, Any] = {"after_seconds": elapsed}
        if expired or last["kind"] != DistributedWorkerPowerEventKind.WAKE_SENT:
            # Long after the wait: someone started the PC, Ohana did not.
            detail = (
                {"late": True, "after_seconds": elapsed}
                if elapsed <= LATE_ANSWER_SECONDS
                else {"manual": True}
            )
        self._power_event_locked(
            worker_id,
            DistributedWorkerPowerEventKind.WORKER_ONLINE,
            now,
            detail,
        )

    def _power_event_locked(
        self,
        worker_id: str,
        kind: DistributedWorkerPowerEventKind,
        now: datetime,
        detail: dict[str, Any],
    ) -> None:
        self._connection.execute(
            """INSERT INTO distributed_worker_power_events
            (worker_id, occurred_at, kind, detail_json) VALUES (?, ?, ?, ?)""",
            (worker_id, self._timestamp(now), kind.value, self._json(detail)),
        )
        self._connection.execute(
            """DELETE FROM distributed_worker_power_events
            WHERE worker_id = ? AND event_id NOT IN (
                SELECT event_id FROM distributed_worker_power_events
                WHERE worker_id = ? ORDER BY event_id DESC LIMIT ?)""",
            (worker_id, worker_id, POWER_EVENT_RETENTION),
        )

    def _power_events_locked(
        self, worker_id: str, limit: int = POWER_EVENTS_SHOWN
    ) -> list[DistributedWorkerPowerEvent]:
        rows = self._connection.execute(
            """SELECT occurred_at, kind, detail_json
            FROM distributed_worker_power_events
            WHERE worker_id = ? ORDER BY event_id DESC LIMIT ?""",
            (worker_id, limit),
        ).fetchall()
        return [
            DistributedWorkerPowerEvent(
                occurred_at=self._parse_timestamp(row["occurred_at"]),
                kind=DistributedWorkerPowerEventKind(row["kind"]),
                detail=json.loads(row["detail_json"]),
            )
            for row in rows
        ]

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
