"""Job-bound access to bounded INFRA-01 and HAOS log sources."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from administration.jobs import DistributedJobRepository
from plugins.backup.backup_config import BackupConfig
from plugins.backup.backup_secrets import resolve_backup_secret

LOG_JOB_TYPES = ("logs.health_check", "logs.investigate")
LOG_SOURCE_IDS = frozenset({"infra-01", "ha-01", "linky-01", "zwave-01"})
_INFRA_JOURNAL_UNITS = ("ohana-agent.service", "ohana-vision.service")
JournalReader = Callable[[str, str, int], tuple[str, bool]]


def _journal_timestamp(value: str) -> str:
    """Convert a validated job timestamp to journalctl's unambiguous epoch form."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError("Invalid INFRA-01 journal window timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("INFRA-01 journal window timestamp must include a timezone")
    return f"@{parsed.timestamp():.6f}"


def read_infra_journal(
    window_started_at: str,
    window_ended_at: str,
    max_bytes: int,
) -> tuple[str, bool]:
    """Read a bounded tail of the Agent and Vision systemd journals."""
    command = ["journalctl"]
    for unit in _INFRA_JOURNAL_UNITS:
        command.extend(("--unit", unit))
    command.extend(
        (
            "--since",
            _journal_timestamp(window_started_at),
            "--until",
            _journal_timestamp(window_ended_at),
            "--lines",
            "10000",
            "--output",
            "short-iso-precise",
            "--no-pager",
            "--quiet",
        )
    )
    try:
        completed = subprocess.run(  # noqa: S603 - command and units are fixed.
            command,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Unable to read INFRA-01 journal: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:500]
        raise RuntimeError(
            "Unable to read INFRA-01 journal" + (f": {detail}" if detail else "")
        )

    payload = completed.stdout
    truncated = len(payload) > max_bytes
    if truncated:
        payload = payload[-max_bytes:]
        first_line_end = payload.find(b"\n")
        if first_line_end >= 0:
            payload = payload[first_line_end + 1 :]
    return payload.decode("utf-8", errors="replace"), truncated


@dataclass(slots=True)
class LogSourceBroker:
    """Reveal one bounded log source only to the owning worker attempt."""

    config: BackupConfig
    repository: DistributedJobRepository
    journal_reader: JournalReader = read_infra_journal

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
        if source_id == "infra-01":
            max_bytes_key = (
                "max_bytes_per_source"
                if job.type == "logs.health_check"
                else "max_bytes"
            )
            content, truncated = self.journal_reader(
                str(job.parameters["window_started_at"]),
                str(job.parameters["window_ended_at"]),
                int(job.parameters[max_bytes_key]),
            )
            return {
                "schema_version": 1,
                "source": source_id,
                "transport": "inline",
                "content": content,
                "truncated": truncated,
            }
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
