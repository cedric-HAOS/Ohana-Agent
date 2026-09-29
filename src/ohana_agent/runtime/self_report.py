"""Phase 5 hardening: the Agent's own detail for the Ohana view in Vision.

Vitals say whether each component still works; this report says how well:
scheduler lateness, queue lengths, storage and its growth, retention and the
available version. Everything is read on demand, nothing is written.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ohana_agent.runtime.release_check import ReleaseCheck, compare_versions
from ohana_agent.scheduler import Scheduler
from ohana_agent.tsunade.local_time import paris_iso, paris_now, to_paris

# A tick every second: more due tasks than this, or no tick for a minute,
# means the scheduler is behind.
OVERDUE_TASKS_LATE = 3
TICK_SILENCE_LATE_SECONDS = 60
OUTBOX_BACKLOG_HIGH = 500


class AgentSelfReport:
    """Compose the report from the pieces the Agent already owns."""

    def __init__(
        self,
        *,
        scheduler: Scheduler,
        data_directory: Path,
        agent_version: str,
        job_vitals: Callable[[], dict[str, Any]] | None = None,
        outbox_pending: Callable[[], int] | None = None,
        vision_status: Callable[[], dict[str, Any] | None] | None = None,
        storage_growth: Callable[[], dict[str, Any] | None] | None = None,
        release_check: ReleaseCheck | None = None,
        clock: Callable[[], datetime] = paris_now,
    ) -> None:
        self.scheduler = scheduler
        self.data_directory = Path(data_directory)
        self.agent_version = agent_version
        self.job_vitals = job_vitals
        self.outbox_pending = outbox_pending
        self.vision_status = vision_status
        self.storage_growth = storage_growth
        self.release_check = release_check
        self.clock = clock

    def snapshot(self) -> dict[str, Any]:
        now = self.clock()
        return {
            "schema_version": 1,
            "generated_at": paris_iso(now),
            "scheduler": self._scheduler(now),
            "queues": self._queues(),
            "storage": self._storage(),
            "versions": self._versions(),
        }

    def _scheduler(self, now: datetime) -> dict[str, Any]:
        tasks = [task for task in self.scheduler.list_tasks() if task.enabled]
        overdue = len(self.scheduler.due_tasks()) if self.scheduler.running else 0
        runtime = self.scheduler.runtime
        last_tick = runtime.last_tick_at
        silence = (
            max((now - to_paris(last_tick)).total_seconds(), 0.0)
            if last_tick is not None
            else None
        )
        late = overdue >= OVERDUE_TASKS_LATE or (
            silence is not None and silence > TICK_SILENCE_LATE_SECONDS
        )
        return {
            "state": "late" if late else "on_time",
            "running": self.scheduler.running,
            "enabled_tasks": len(tasks),
            "overdue_tasks": overdue,
            "last_tick_at": paris_iso(last_tick) if last_tick else None,
            "tick_silence_seconds": int(silence) if silence is not None else None,
            "tasks_executed": runtime.statistics.tasks_executed,
            "tasks_failed": runtime.statistics.tasks_failed,
        }

    def _queues(self) -> dict[str, Any]:
        outbox = self.outbox_pending() if self.outbox_pending else None
        jobs = self.job_vitals() if self.job_vitals else None
        return {
            "vision_outbox": {
                "pending": outbox,
                "state": (
                    "unknown"
                    if outbox is None
                    else "backlog"
                    if outbox >= OUTBOX_BACKLOG_HIGH
                    else "ok"
                ),
            },
            "jobs": jobs,
        }

    def _storage(self) -> dict[str, Any]:
        files = []
        if self.data_directory.is_dir():
            for path in sorted(self.data_directory.iterdir()):
                if path.is_file() and ".db" in path.name:
                    files.append({"name": path.name, "bytes": path.stat().st_size})
        try:
            usage = shutil.disk_usage(self.data_directory)
            disk = {
                "total_bytes": usage.total,
                "free_bytes": usage.free,
                "used_percent": round(usage.used / usage.total * 100, 1),
            }
        except OSError:
            disk = None
        return {
            "directory": str(self.data_directory),
            "files": files,
            "total_bytes": sum(item["bytes"] for item in files),
            "disk": disk,
            "growth": self.storage_growth() if self.storage_growth else None,
        }

    def _versions(self) -> dict[str, Any]:
        release = self.release_check.snapshot() if self.release_check else None
        recommended = (release or {}).get("recommended") or {}
        vision = self.vision_status() if self.vision_status else None
        vision_version = (vision or {}).get("version")
        return {
            "checked_at": (release or {}).get("checked_at"),
            "error": (release or {}).get("error"),
            "platform_recommended": recommended.get("platform_version"),
            "agent": {
                "installed": self.agent_version,
                "recommended": recommended.get("agent_version"),
                "state": compare_versions(
                    self.agent_version, recommended.get("agent_version")
                ),
            },
            # Compared by Vision with each worker's own version.
            "katsuyu_latest": recommended.get("katsuyu_version"),
            "vision": {
                "installed": vision_version,
                "recommended": recommended.get("vision_version"),
                "state": compare_versions(
                    vision_version, recommended.get("vision_version")
                ),
            },
        }
