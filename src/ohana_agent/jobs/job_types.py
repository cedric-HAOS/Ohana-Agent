"""Job types, statuses and errors shared by the distributed job modules."""

from __future__ import annotations

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

LOCAL_TIMEZONE = ZoneInfo("Europe/Paris")
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
    {"backup.infra", "logs.health_check", "logs.investigate"}
)
# Results Tsunade must record before the job is settled (resumed at restart).
COMPLETION_PROCESSED_TYPES = frozenset(
    {"logs.health_check", "logs.investigate", "ai.inference", "trends.history_backfill"}
)
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class DistributedJobConflictError(RuntimeError):
    """Raised when a job operation conflicts with its durable state."""
