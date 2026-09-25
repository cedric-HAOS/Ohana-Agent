"""SQLite schema and migrations of the distributed job database."""

from __future__ import annotations


class DistributedJobSchema:
    """SQLite schema and migrations of the distributed job database."""

    def _initialize(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS distributed_jobs (
                    job_id TEXT PRIMARY KEY,
                    protocol_version INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    timeout_seconds INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    result_json TEXT,
                    result_sha256 TEXT,
                    error_json TEXT,
                    worker_id TEXT,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    lease_expires_at TEXT,
                    request_sha256 TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    progress_json TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in self._connection.execute(
                    "PRAGMA table_info(distributed_jobs)"
                ).fetchall()
            }
            if "progress_json" not in columns:
                self._connection.execute(
                    "ALTER TABLE distributed_jobs ADD COLUMN progress_json TEXT"
                )
            if "completion_processed" not in columns:
                self._connection.execute(
                    "ALTER TABLE distributed_jobs ADD COLUMN "
                    "completion_processed INTEGER NOT NULL DEFAULT 1"
                )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_distributed_jobs_dispatch
                ON distributed_jobs(status, created_at)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_distributed_jobs_type_created
                ON distributed_jobs(type, created_at DESC)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_distributed_jobs_lease
                ON distributed_jobs(status, lease_expires_at)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS distributed_job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    previous_status TEXT,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES distributed_jobs(job_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS distributed_workers (
                    worker_id TEXT PRIMARY KEY,
                    protocol_version INTEGER NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    worker_version TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    woken_by_ohana INTEGER NOT NULL DEFAULT 0,
                    wake_requested_at TEXT,
                    wake_deadline_at TEXT,
                    wake_on_lan_mac_address TEXT
                )
                """
            )
            worker_columns = {
                row["name"]
                for row in self._connection.execute(
                    "PRAGMA table_info(distributed_workers)"
                ).fetchall()
            }
            if "woken_by_ohana" not in worker_columns:
                self._connection.execute(
                    "ALTER TABLE distributed_workers "
                    "ADD COLUMN woken_by_ohana INTEGER NOT NULL DEFAULT 0"
                )
            if "wake_requested_at" not in worker_columns:
                self._connection.execute(
                    "ALTER TABLE distributed_workers ADD COLUMN wake_requested_at TEXT"
                )
            if "wake_deadline_at" not in worker_columns:
                self._connection.execute(
                    "ALTER TABLE distributed_workers ADD COLUMN wake_deadline_at TEXT"
                )
            if "wake_on_lan_mac_address" not in worker_columns:
                self._connection.execute(
                    "ALTER TABLE distributed_workers "
                    "ADD COLUMN wake_on_lan_mac_address TEXT"
                )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS distributed_worker_pairings (
                    pairing_id TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    protocol_version INTEGER NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    worker_version TEXT NOT NULL,
                    polling_secret_sha256 TEXT NOT NULL,
                    verification_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    approved_at TEXT,
                    consumed_at TEXT
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_worker_pairings_status
                ON distributed_worker_pairings(status, expires_at)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS distributed_worker_credentials (
                    worker_id TEXT PRIMARY KEY,
                    token_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                )
                """
            )
