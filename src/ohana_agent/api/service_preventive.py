"""Preventive maintenance, restore tests and archive checks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ohana_agent.jobs.job_types import (
    LOCAL_TIMEZONE,
    DistributedJobConflictError,
)
from ohana_agent.tsunade.local_time import PARIS, paris_iso, paris_now, to_paris
from ohana_agent.tsunade.preventive_backup import RESTORE_TEST_MAX_AGE_DAYS

LOGGER = logging.getLogger(__name__)
PREVENTIVE_HISTORY_SOURCE = "ha-01"
PREVENTIVE_BACKFILL_DAYS = 30
PREVENTIVE_BACKFILL_TIMEOUT_SECONDS = 12 * 3600


class PreventiveServiceMixin:
    """Preventive maintenance, restore tests and archive checks."""

    def mute_preventive(self, payload: dict[str, Any]) -> object:
        """Fewer useless alerts: set one drift aside for a number of days."""
        if self.preventive_monitor is None:
            raise LookupError("La maintenance préventive est indisponible")
        days = payload.get("days", 30)
        if isinstance(days, bool) or not isinstance(days, int):
            raise ValueError("days must be an integer")
        return self.preventive_monitor.mute(
            str(payload.get("rule", "")),
            str(payload.get("subject", "")),
            days=days,
            title=str(payload.get("title", "")),
        )

    def unmute_preventive(self, payload: dict[str, Any]) -> object:
        if self.preventive_monitor is None:
            raise LookupError("La maintenance préventive est indisponible")
        return self.preventive_monitor.unmute(
            str(payload.get("rule", "")), str(payload.get("subject", ""))
        )

    def read_restore_tests(self) -> object:
        """Phase 10: backup targets and the restoration tests declared for them."""
        if self.preventive_monitor is None:
            raise LookupError("La maintenance préventive est indisponible")
        return {
            "schema_version": 1,
            "generated_at": paris_iso(paris_now()),
            "max_age_days": RESTORE_TEST_MAX_AGE_DAYS,
            "icloud": self.preventive_monitor.icloud_status(),
            "targets": self.preventive_monitor.backup_posture(),
        }

    def request_archive_check(self, payload: dict[str, Any]) -> object:
        """Phase 10: read the latest archive again now, in the background."""
        if self.archive_integrity is None:
            raise LookupError("La vérification des archives est indisponible")
        target = payload.get("target")
        if target is not None and not isinstance(target, str):
            raise ValueError("target must be a string")
        started = self.archive_integrity.request(target.strip() if target else None)
        return {"started": started, "busy": not started}

    def declare_restore_test(self, payload: dict[str, Any]) -> object:
        """Keep the outcome of a restoration the owner performed for real."""
        if self.preventive_monitor is None:
            raise LookupError("La maintenance préventive est indisponible")
        tested_at = payload.get("tested_at")
        if tested_at is not None:
            try:
                tested_at = datetime.fromisoformat(str(tested_at))
            except ValueError as error:
                raise ValueError("tested_at must be an ISO 8601 date") from error
            if tested_at.tzinfo is None:
                tested_at = tested_at.replace(tzinfo=LOCAL_TIMEZONE)
        return self.preventive_monitor.declare_restore_test(
            target=str(payload.get("target", "")),
            outcome=str(payload.get("outcome", "")),
            tested_at=tested_at,
            reference=str(payload.get("reference", "")),
            note=str(payload.get("note", "")),
        )

    def read_preventive_summary(self) -> object:
        """Phase 4: the short synthesis and the detail of each drift rule."""
        if self.preventive_monitor is None:
            raise LookupError("La maintenance préventive est indisponible")
        summary = self.preventive_monitor.summary()
        summary["backfill"] = self._preventive_backfill_state()
        return summary

    def _preventive_backfill_available(self) -> bool:
        broker = self.log_source_broker
        return (
            self.job_repository is not None
            and self.preventive_monitor is not None
            and broker is not None
            and any(
                target.id == PREVENTIVE_HISTORY_SOURCE and target.enabled
                for target in broker.config.targets
            )
        )

    def _preventive_backfill_state(self) -> dict[str, Any] | None:
        if not self._preventive_backfill_available():
            return None
        assert self.job_repository is not None
        latest = self.job_repository.latest_for_incident(
            "trends.history_backfill", None
        )
        if latest is None:
            return {"available": True, "job": None}
        result = latest.result or {}
        return {
            "available": True,
            "job": {
                "job_id": str(latest.job_id),
                "status": latest.status.value,
                "created_at": paris_iso(latest.created_at),
                "finished_at": (
                    paris_iso(latest.finished_at) if latest.finished_at else None
                ),
                "days": len(result.get("days", [])),
                "entity_id": result.get("entity_id"),
                "error": (latest.error.message if latest.error else None),
            },
        }

    def request_preventive_backfill(
        self, *, now: datetime | None = None, automatic: bool = False
    ) -> object:
        """Ask Katsuyu to rebuild past daily values from Home Assistant.

        Automatic requests only run when a past day of the rule window is
        missing and no request was made in the last 24 hours; without Katsuyu
        the simple checks keep working on what the Agent measured itself.
        """
        if not self._preventive_backfill_available():
            if automatic:
                return None
            raise LookupError("Le rattrapage de l'historique est indisponible")
        assert self.job_repository is not None
        assert self.preventive_monitor is not None
        current = to_paris(now) if now is not None else paris_now()
        node = self.agent_node_id or "infra-01"
        active = self.job_repository.active_for_incident(
            "trends.history_backfill", None
        )
        if active is not None:
            if automatic:
                return None
            raise DistributedJobConflictError(
                f"history backfill is already active as job {active.job_id}"
            )
        if automatic:
            if not self.preventive_monitor.missing_days(
                node, "disk_percent", now=current
            ):
                return None
            latest = self.job_repository.latest_for_incident(
                "trends.history_backfill", None
            )
            if latest is not None and current - to_paris(latest.created_at) < timedelta(
                hours=24
            ):
                return None
        # A Paris calendar day: the offset of midnight, not of now, applies.
        midnight = current.astimezone(PARIS).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return self.create_job(
            {
                "protocol_version": 1,
                "job_id": str(uuid4()),
                "type": "trends.history_backfill",
                "created_at": current.isoformat(),
                "parameters": {
                    "source": PREVENTIVE_HISTORY_SOURCE,
                    "node_id": node,
                    "metric": "disk_percent",
                    "unique_id": "ohana_host_disk_usage",
                    "window_started_at": (
                        midnight - timedelta(days=PREVENTIVE_BACKFILL_DAYS)
                    ).isoformat(),
                    "window_ended_at": midnight.isoformat(),
                },
                # Katsuyu may sleep until its next wake: the job waits for it.
                "timeout": PREVENTIVE_BACKFILL_TIMEOUT_SECONDS,
            }
        )

    def read_history_source(
        self,
        job_id: str,
        worker_id: str,
        attempt: int,
        source_id: str,
    ) -> object:
        """Home Assistant access bound to one running backfill attempt."""
        if self.log_source_broker is None:
            raise LookupError("Distributed history sources are unavailable")
        return self.log_source_broker.history_descriptor(
            job_id, worker_id, attempt, source_id
        )
