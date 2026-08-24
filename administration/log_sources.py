"""Job-bound access descriptors for direct Katsuyu-to-HAOS log retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from administration.jobs import DistributedJobRepository
from plugins.backup.backup_config import BackupConfig
from plugins.backup.backup_secrets import resolve_backup_secret

LOG_JOB_TYPES = ("logs.health_check", "logs.investigate")
LOG_SOURCE_IDS = frozenset({"ha-01", "linky-01", "zwave-01"})


@dataclass(slots=True)
class LogSourceBroker:
    """Reveal one configured HAOS credential only to the owning worker attempt."""

    config: BackupConfig
    repository: DistributedJobRepository

    def descriptor(
        self,
        job_id: str,
        worker_id: str,
        attempt: int,
        source_id: str,
    ) -> dict[str, object]:
        if source_id not in LOG_SOURCE_IDS:
            raise ValueError(f"unsupported log source: {source_id}")
        job = self.repository.authorize_job_transfer(
            job_id,
            worker_id=worker_id,
            attempt=attempt,
            job_type=LOG_JOB_TYPES,
        )
        requested = (
            job.parameters.get("sources", [])
            if job.type == "logs.health_check"
            else [job.parameters.get("source")]
        )
        if source_id not in requested:
            raise ValueError("log source is not authorized by this job")
        target = next(
            (
                candidate
                for candidate in self.config.targets
                if candidate.id == source_id
            ),
            None,
        )
        if target is None or not target.enabled:
            raise LookupError(f"configured HAOS log source not found: {source_id}")
        token = target.token
        if token is None and target.token_environment_variable:
            token = resolve_backup_secret(
                self.config.environment_file,
                target.token_environment_variable,
            )
        if not token:
            raise RuntimeError(f"Home Assistant token is missing for {source_id}")
        return {
            "schema_version": 1,
            "source": source_id,
            "base_url": target.url.rstrip("/"),
            "url": (
                f"{target.url.rstrip('/')}/api/hassio/core/logs/latest"
                "?lines=10000&no_colors=1"
            ),
            "access_token": token,
            "verify_tls": target.verify_tls,
            "timeout_seconds": min(max(float(target.timeout), 5.0), 60.0),
            "addon_name_patterns": {
                "ha-01": [],
                "linky-01": ["teleinfo2mqtt", "teleinfo", "linky"],
                "zwave-01": ["z-wave js", "zwave js", "zwavejs", "zwave"],
            }[source_id],
        }
