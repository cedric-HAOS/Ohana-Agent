"""Distributed jobs, Katsuyu workers, Wake-on-LAN and backup transfers."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from datetime import time as clock_time
from typing import Any

from ohana_agent.jobs.job_types import (
    AUTOMATIC_WAKE_JOB_TYPES,
    DEFERRED_TO_BATCH_JOB_TYPES,
    LOCAL_TIMEZONE,
    DistributedJobConflictError,
)
from ohana_agent.tsunade.expertise_catalog import (
    TsunadeExpertiseConflictError,
)

LOGGER = logging.getLogger(__name__)
# A sleeping worker never polls: deadlines are also settled on this cadence.
JOB_SETTLEMENT_INTERVAL = timedelta(seconds=30)


class JobServiceMixin:
    """Distributed jobs, Katsuyu workers, Wake-on-LAN and backup transfers."""

    def create_job(self, payload: dict[str, Any]) -> object:
        """Validate and queue one explicitly typed distributed job."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        payload = self._extend_job_timeout_until_planned_wake(payload)
        job = self.job_repository.create(payload)
        self.dispatch_due_wake_requests()
        return job

    def _extend_job_timeout_until_planned_wake(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Keep grouped Katsuyu jobs alive until the planned wake boundary."""
        if (
            not self.wake_enabled
            or self.wake_planned_window_end_hour >= 24
            or payload.get("type") not in AUTOMATIC_WAKE_JOB_TYPES
        ):
            return payload
        try:
            timeout_seconds = int(payload["timeout"])
            created_at = datetime.fromisoformat(str(payload["created_at"]))
        except (KeyError, TypeError, ValueError):
            return payload
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            created_at = created_at.replace(tzinfo=LOCAL_TIMEZONE)
        current = created_at.astimezone(self.wake_schedule_timezone)
        in_window = (
            self.wake_planned_window_start_hour
            <= current.hour
            < self.wake_planned_window_end_hour
        )
        if not in_window and payload.get("type") not in DEFERRED_TO_BATCH_JOB_TYPES:
            return payload
        # Created in the window: today's batch. Created later in the day (an
        # incident while Bubule is off): tomorrow's.
        batch_day = current.date() + timedelta(days=0 if in_window else 1)
        if not in_window and current.hour < self.wake_planned_window_start_hour:
            batch_day = current.date()
        planned_wake = datetime.combine(
            batch_day,
            clock_time(self.wake_planned_window_end_hour),
            tzinfo=self.wake_schedule_timezone,
        )
        # Subtract instants, not wall-clock times: a day can have 23 or 25 hours.
        seconds_until_wake = math.ceil(
            (planned_wake.astimezone(UTC) - current.astimezone(UTC)).total_seconds()
        )
        if seconds_until_wake <= 0:
            return payload
        extended = dict(payload)
        extended["timeout"] = (
            timeout_seconds + seconds_until_wake + self.wake_timeout_seconds
        )
        return extended

    def settle_expired_jobs(self, now: datetime | None = None) -> None:
        """Record elapsed deadlines while no worker or page reads the queue."""
        if self.job_repository is None:
            return
        current = now or self.job_repository.now()
        if (
            self._last_job_settlement is not None
            and current - self._last_job_settlement < JOB_SETTLEMENT_INTERVAL
        ):
            return
        # A busy worker cycle settles the queue itself; never stall the scheduler.
        if not self._worker_cycle_lock.acquire(blocking=False):
            return
        try:
            self._last_job_settlement = current
            self._refresh_failed_jobs()
        finally:
            self._worker_cycle_lock.release()

    def dispatch_due_wake_requests(self, now: datetime | None = None) -> None:
        """Wake one worker at the local daily Katsuyu batch boundary."""
        if self.job_repository is None:
            return
        self._retry_unanswered_wake()
        current = (now or self.job_repository.now()).astimezone(
            self.wake_schedule_timezone
        )
        if (
            self.wake_planned_window_end_hour < 24
            and current.hour != self.wake_planned_window_end_hour
        ):
            return
        batch_date = current.date()
        if self._last_planned_wake_date == batch_date:
            return
        woke_worker = False
        for job_type in self.job_repository.wake_ready_job_types(
            batch_window_seconds=0,
            job_types=AUTOMATIC_WAKE_JOB_TYPES,
        ):
            woke_worker = self._wake_compatible_worker(job_type) or woke_worker
        if woke_worker:
            self._last_planned_wake_date = batch_date

    def _retry_unanswered_wake(self) -> None:
        """Wake again a PC that stayed silent, a few times, while work waits."""
        if (
            self.job_repository is None
            or not self.wake_enabled
            or self.wake_sender is None
        ):
            if self.job_repository is not None:
                self.job_repository.settle_unanswered_wakes(
                    max_attempts=self.wake_max_unanswered_attempts
                )
            return
        worker = self.job_repository.unanswered_wake_retry(
            retry_delay_seconds=self.wake_unanswered_retry_seconds,
            max_attempts=self.wake_max_unanswered_attempts,
        )
        if worker is None:
            return
        mac_address = worker.wake_on_lan_mac_address or (
            self.wake_mac_address if worker.worker_id == self.wake_worker_id else None
        )
        if mac_address is not None:
            self._send_and_mark_wake(worker.worker_id, mac_address, trigger="retry")

    def _send_and_mark_wake(
        self, worker_id: str, mac_address: str, *, trigger: str
    ) -> bool:
        """Send one Wake-on-LAN and journal it, or journal why it was not sent."""
        assert self.job_repository is not None  # noqa: S101
        try:
            self._send_wake_on_lan(mac_address)
        except (OSError, ValueError) as error:
            LOGGER.exception(
                "Unable to send Wake-on-LAN for Katsuyu worker %s", worker_id
            )
            self.job_repository.record_wake_failure(
                worker_id, str(error), trigger=trigger
            )
            return False
        self.job_repository.mark_worker_waking(
            worker_id,
            timeout_seconds=self.wake_timeout_seconds,
            trigger=trigger,
        )
        return True

    def request_manual_log_health_check(self) -> object:
        """A control asked from Vision wakes Katsuyu now, not at 05:00."""
        job = self.request_log_health_check()
        self._wake_compatible_worker(
            "logs.health_check", trigger="manual_check", ignore_interval=True
        )
        return job

    def _wake_compatible_worker(
        self,
        job_type: str,
        *,
        trigger: str = "queued_jobs",
        ignore_interval: bool = False,
    ) -> bool:
        """Wake one unavailable compatible worker using its advertised WOL MAC."""
        if (
            self.job_repository is None
            or not self.wake_enabled
            or self.wake_sender is None
        ):
            return False
        worker = self.job_repository.wake_candidate(
            job_type,
            minimum_interval_seconds=(
                0 if ignore_interval else self.wake_minimum_interval_seconds
            ),
            fallback_worker_id=self.wake_worker_id,
            fallback_mac_address=self.wake_mac_address,
        )
        if worker is None or worker.wake_on_lan_mac_address is None:
            return False
        return self._send_and_mark_wake(
            worker.worker_id,
            worker.wake_on_lan_mac_address,
            trigger=trigger,
        )

    def read_job(self, job_id: str) -> object:
        """Read the current durable state of one job."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.get(job_id)

    def cancel_job(self, job_id: str) -> object:
        """Cancel one job through the Tsunade control plane."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.cancel(job_id)

    def claim_job(self, payload: dict[str, Any]) -> object:
        """Lease the oldest compatible job to Katsuyu."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.claim(
            payload,
            # Legacy workers cannot re-check the queue after publishing results.
            shutdown_after_completion=False,
        )

    def next_worker_job(self, payload: dict[str, Any]) -> object:
        """Settle results before claiming work or allowing shutdown."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        with self._worker_cycle_lock:
            if self.followups is not None:
                self.followups.resume()
            for job in self.job_repository.pending_completions():
                self._process_job_completion(job)
            return self.job_repository.claim(
                payload,
                settle=True,
                shutdown_after_completion=self.wake_shutdown_after_completion,
            )

    def register_worker(
        self,
        payload: dict[str, Any],
        *,
        previous_worker_id: str | None = None,
    ) -> object:
        """Register Katsuyu and its finite capabilities."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        if (
            payload.get("worker_id") == self.wake_worker_id
            and payload.get("wake_on_lan_mac_address") is None
            and self.wake_mac_address is not None
        ):
            payload = dict(payload)
            payload["wake_on_lan_mac_address"] = self.wake_mac_address
        return self.job_repository.register_worker(
            payload,
            previous_worker_id=previous_worker_id,
        )

    def report_worker_runtimes(self, payload: dict[str, Any]) -> object:
        """Record the local runtimes Katsuyu checked (Phase 5 vitals)."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.report_worker_runtimes(payload)

    def report_worker_power(self, payload: dict[str, Any]) -> object:
        """Record whether Katsuyu shut its PC down or kept it on (Phase 6)."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.report_worker_power(payload)

    def list_workers(self) -> object:
        """List the worker registrations visible to Tsunade."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.list_workers()

    def read_wake_on_lan(self) -> object:
        """Expose the effective Wake-on-LAN policy without duplicating worker data."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return {
            "schema_version": 1,
            "enabled": self.wake_enabled,
            "broadcast_address": self.wake_broadcast_address,
            "port": self.wake_port,
            "wait_timeout_seconds": self.wake_timeout_seconds,
            "available_for_seconds": self.wake_available_for_seconds,
            "packet_burst_count": self.wake_packet_burst_count,
            "burst_interval_seconds": self.wake_burst_interval_seconds,
            "retry_count": self.wake_retry_count,
            "retry_delay_seconds": self.wake_retry_delay_seconds,
            "batch_window_seconds": self.wake_batch_window_seconds,
            "planned_window_start_hour": self.wake_planned_window_start_hour,
            "planned_window_end_hour": self.wake_planned_window_end_hour,
            "schedule_timezone": self.wake_schedule_timezone_name,
            "minimum_interval_seconds": self.wake_minimum_interval_seconds,
            "shutdown_after_completion": self.wake_shutdown_after_completion,
        }

    def write_wake_on_lan(self, payload: dict[str, Any]) -> object:
        """Enable or disable Agent-owned Wake-on-LAN policy."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")

        if set(payload) != {"enabled"}:
            raise ValueError("Wake-on-LAN update only accepts enabled")

        enabled = payload["enabled"]

        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")

        if enabled:
            workers = self.job_repository.list_workers()

            if not any(worker.wake_on_lan_mac_address for worker in workers.workers):
                raise DistributedJobConflictError(
                    "Wake-on-LAN cannot be enabled because no "
                    "worker has advertised a Wake-on-LAN MAC "
                    "address"
                )

        if self.on_wake_enabled_changed is not None:
            self.on_wake_enabled_changed(enabled)

        self.wake_enabled = enabled

        return self.read_wake_on_lan()

    def wake_worker(self, worker_id: str) -> object:
        """Send one explicit Wake-on-LAN test to a registered Katsuyu worker."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        if not self.wake_enabled or self.wake_sender is None:
            raise DistributedJobConflictError("Wake-on-LAN is disabled")
        worker = self.job_repository.worker_availability(worker_id)
        mac_address = worker.wake_on_lan_mac_address
        if (
            mac_address is None
            and worker.worker_id == self.wake_worker_id
            and self.wake_mac_address is not None
        ):
            mac_address = self.wake_mac_address
        if mac_address is None:
            raise DistributedJobConflictError(
                f"worker {worker_id} has not advertised a Wake-on-LAN MAC address"
            )
        if worker.availability.value == "AVAILABLE":
            raise DistributedJobConflictError(
                f"worker {worker_id} is already available"
            )
        if worker.availability.value == "WAKING":
            return worker
        try:
            self._send_wake_on_lan(mac_address)
        except (OSError, ValueError) as error:
            self.job_repository.record_wake_failure(
                worker.worker_id, str(error), trigger="manual"
            )
            raise
        self.job_repository.mark_worker_waking(
            worker.worker_id,
            timeout_seconds=self.wake_timeout_seconds,
            trigger="manual",
        )
        return self.job_repository.worker_availability(worker.worker_id)

    def _send_wake_on_lan(self, mac_address: str) -> None:
        """Send Wake-on-LAN with bounded retries around the sender burst."""
        if self.wake_sender is None:
            raise DistributedJobConflictError("Wake-on-LAN is disabled")

        attempts = self.wake_retry_count + 1
        for attempt in range(attempts):
            try:
                self.wake_sender(mac_address)
                return
            except (OSError, ValueError):
                if attempt >= attempts - 1:
                    raise
                if self.wake_retry_delay_seconds > 0:
                    self.wake_retry_sleeper(self.wake_retry_delay_seconds)

    def create_worker_pairing(self, payload: dict[str, Any]) -> object:
        """Open a bounded Katsuyu pairing request for later approval."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        pairing = self.job_repository.create_pairing(payload)
        return pairing.model_copy(update={"tls_ca_sha256": self.worker_ca_sha256})

    def list_worker_pairings(self) -> object:
        """List pairing requests visible to the administration plane."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        collection = self.job_repository.list_pairings()
        return collection.model_copy(
            update={
                "pairings": [
                    pairing.model_copy(update={"tls_ca_sha256": self.worker_ca_sha256})
                    for pairing in collection.pairings
                ]
            }
        )

    def read_worker_trust(self) -> object:
        """Return the public CA material used by the dedicated worker listener."""
        if self.worker_ca_certificate_pem is None or self.worker_ca_sha256 is None:
            raise LookupError("Katsuyu HTTPS trust is unavailable")
        return {
            "schema_version": 1,
            "ca_certificate_pem": self.worker_ca_certificate_pem,
            "ca_sha256": self.worker_ca_sha256,
        }

    def approve_worker_pairing(self, pairing_id: str) -> object:
        """Approve one verification code checked by the administrator."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.approve_pairing(pairing_id)

    def reject_worker_pairing(self, pairing_id: str) -> object:
        """Reject one untrusted or obsolete pairing request."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.reject_pairing(pairing_id)

    def poll_worker_pairing(self, pairing_id: str, payload: dict[str, Any]) -> object:
        """Let the originating installer retrieve its credential once."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.poll_pairing(pairing_id, payload)

    def heartbeat_job(self, job_id: str, payload: dict[str, Any]) -> object:
        """Renew a job lease for its current Katsuyu attempt."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.heartbeat(job_id, payload)

    def complete_job(self, job_id: str, payload: dict[str, Any]) -> object:
        """Record a verified result from the current Katsuyu attempt."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        with self._worker_cycle_lock:
            job = self.job_repository.complete(job_id, payload)
            for pending in self.job_repository.pending_completions():
                if str(pending.job_id) == job_id:
                    self._process_job_completion(pending)
            return job

    def _settle_for_read(
        self, *, refresh: bool = True, reconcile: bool = False
    ) -> None:
        """Settle the queue before a read, unless a worker cycle is doing it.

        Processing one Katsuyu result held the worker cycle lock for 38 s on
        INFRA-01 (28 September, slow SD card): page reads waiting for it went
        past Vision's 10 s timeout and Vision answered 502. The busy cycle
        settles the queue itself and the wake task settles failures every 30 s.
        """
        if not self._worker_cycle_lock.acquire(blocking=False):
            return
        try:
            if refresh:
                self._refresh_failed_jobs()
            if reconcile:
                self._reconcile_followup_proposals()
        finally:
            self._worker_cycle_lock.release()

    def _refresh_failed_jobs(self) -> None:
        """Expose all terminal failures even when no worker polls again."""
        if self.job_repository is None:
            return
        with self._worker_cycle_lock:
            while True:
                pending = self.job_repository.pending_completions(failures_only=True)
                if not pending:
                    return
                for job in pending:
                    self._process_job_completion(job)

    def _process_job_completion(self, job: Any) -> None:
        """Commit decisions and follow-up jobs before releasing idle workers."""
        assert self.job_repository is not None
        if (
            job.status.value == "SUCCEEDED"
            and job.result is not None
            and self.incident_repository is not None
        ):
            incident_id = job.parameters.get("incident_id")
            if job.type == "logs.health_check":
                affected = self.incident_repository.record_log_health(
                    job.job_id,
                    job.result,
                    incident_id=incident_id,
                )
                if self.expertise_service is not None:
                    for target in affected:
                        try:
                            target_incident = self.incident_repository.get(target)
                            if target_incident.expertise_state == "ai_queued":
                                previous = self.job_repository.latest_for_incident(
                                    "ai.inference", str(target)
                                )
                                if previous is not None and previous.status.value in {
                                    "SUCCEEDED",
                                    "FAILED",
                                    "TIMEOUT",
                                    "CANCELLED",
                                }:
                                    self._process_job_completion(previous)
                                elif previous is None:
                                    self.expertise_service.record_ai_failure(
                                        target,
                                        job.job_id,
                                        "Analyse précédente introuvable",
                                    )
                            self.expertise_service.review_log_health(
                                target, job.job_id, job.result
                            )
                        except TsunadeExpertiseConflictError:
                            return
            elif (
                job.type == "trends.history_backfill"
                and self.preventive_monitor is not None
            ):
                self.preventive_monitor.record_backfill(
                    str(job.parameters["node_id"]),
                    str(job.parameters["metric"]),
                    list(job.result.get("days", [])),
                    source="home_assistant",
                )
            elif job.type == "logs.investigate" and incident_id is not None:
                self.incident_repository.record_log_investigation(
                    job.job_id,
                    incident_id,
                    job.result,
                )
            elif job.type == "ai.inference" and incident_id is not None:
                if self.expertise_service is not None:
                    self.expertise_service.record_ai_result(
                        incident_id,
                        job.job_id,
                        job.result,
                        evidence=job.parameters.get("evidence"),
                    )
                    if self.followups is not None:
                        self.followups.consider(job)
        elif (
            job.type == "ai.inference"
            and job.parameters.get("incident_id") is not None
            and self.expertise_service is not None
            and job.status.value in {"FAILED", "TIMEOUT", "CANCELLED"}
        ):
            self.expertise_service.record_ai_failure(
                job.parameters["incident_id"],
                job.job_id,
                job.error.message if job.error is not None else job.status.value,
            )
        if self.followups is not None:
            self.followups.completed(job)
        self.job_repository.mark_completion_processed(str(job.job_id))

    def _reconcile_followup_proposals(self) -> None:
        """Make still-current persisted suggestions actionable after an upgrade."""
        if self.followups is None or self.incident_repository is None:
            return
        assert self.job_repository is not None
        with self._worker_cycle_lock:
            for incident in self.incident_repository.list():
                if (
                    incident.state != "active"
                    or incident.capability_id != "logs.health"
                ):
                    continue
                job = self.job_repository.latest_for_incident(
                    "ai.inference", str(incident.incident_id)
                )
                if job is not None and job.status.value == "SUCCEEDED":
                    self.followups.consider(job)

    def authorize_backup_transfer(
        self, job_id: str, worker_id: str, attempt: int
    ) -> object:
        if self.backup_transfer is None:
            raise LookupError("Distributed INFRA backup transfer is unavailable")
        return self.backup_transfer.authorize(job_id, worker_id, attempt)

    def open_backup_source(self, job_id: str, worker_id: str, attempt: int) -> object:
        if self.backup_transfer is None:
            raise LookupError("Distributed INFRA backup transfer is unavailable")
        return self.backup_transfer.open_source(job_id, worker_id, attempt)

    def receive_backup_artifact(
        self,
        job_id: str,
        worker_id: str,
        attempt: int,
        stream: object,
        size_bytes: int,
        sha256: str,
    ) -> object:
        if self.backup_transfer is None:
            raise LookupError("Distributed INFRA backup transfer is unavailable")
        return self.backup_transfer.receive_artifact(
            job_id,
            worker_id,
            attempt,
            stream,
            size_bytes=size_bytes,
            expected_sha256=sha256,
        )

    def read_log_source(
        self,
        job_id: str,
        worker_id: str,
        attempt: int,
        source_id: str,
    ) -> object:
        """Return one short-lived job-bound descriptor, never raw journals."""
        if self.log_source_broker is None:
            raise LookupError("Distributed log sources are unavailable")
        return self.log_source_broker.descriptor(job_id, worker_id, attempt, source_id)
