"""Job types, statuses and errors shared by the distributed job modules."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from ohana_agent.contracts.administration import (
    AiInferenceParameters,
    AiInferenceResult,
    BackupCompressParameters,
    BackupCompressResult,
    BackupEncryptParameters,
    BackupEncryptResult,
    BackupVerifyParameters,
    BackupVerifyResult,
    DistributedJobStatus,
    InfraBackupParameters,
    InfraBackupResult,
    LogsHealthCheckParameters,
    LogsHealthCheckResult,
    LogsInvestigateParameters,
    LogsInvestigateResult,
    SystemHealthParameters,
    SystemHealthResult,
    TrendsHistoryBackfillParameters,
    TrendsHistoryBackfillResult,
)
from ohana_agent.tsunade.local_time import paris_instant as _paris_instant

LOCAL_TIMEZONE = ZoneInfo("Europe/Paris")


def paris_instant(value: datetime) -> datetime:
    """Paris time with a fixed offset: exact sums and differences (see local_time)."""
    return _paris_instant(value)


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
    "logs.health_check": (LogsHealthCheckParameters, LogsHealthCheckResult),
    "logs.investigate": (LogsInvestigateParameters, LogsInvestigateResult),
    "ai.inference": (AiInferenceParameters, AiInferenceResult),
    "trends.history_backfill": (
        TrendsHistoryBackfillParameters,
        TrendsHistoryBackfillResult,
    ),
}

AUTOMATIC_WAKE_JOB_TYPES = frozenset(
    {"backup.infra", "logs.health_check", "logs.investigate", "ai.inference"}
)
# Work an incident asks for in the daytime: Bubule is off by design, so instead of
# letting it expire after its short timeout it waits for the next 05:00 batch.
# backup.infra is not here: a backup asked by hand must run now or fail visibly.
DEFERRED_TO_BATCH_JOB_TYPES = frozenset(
    {"logs.health_check", "logs.investigate", "ai.inference"}
)
# Results Tsunade must record before the job is settled (resumed at restart).
COMPLETION_PROCESSED_TYPES = frozenset(
    {"logs.health_check", "logs.investigate", "ai.inference", "trends.history_backfill"}
)
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class DistributedJobConflictError(RuntimeError):
    """Raised when a job operation conflicts with its durable state."""
