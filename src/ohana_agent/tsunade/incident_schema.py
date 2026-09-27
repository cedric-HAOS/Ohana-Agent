"""SQLite schema and migrations of the Tsunade control database."""

from __future__ import annotations


class TsunadeIncidentSchema:
    """SQLite schema and migrations of the Tsunade control database."""

    def _migrate_experience_history(self) -> None:
        """Phase 3: attempts, last outcomes and a lifecycle state per repair."""
        columns = {
            row[1]
            for row in self._connection.execute(
                "PRAGMA table_info(tsunade_experiences)"
            )
        }
        if "attempt_count" in columns:
            return
        for statement in (
            "ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0",
            "ADD COLUMN last_success_at TEXT",
            "ADD COLUMN last_failure_at TEXT",
            "ADD COLUMN state TEXT NOT NULL DEFAULT 'active'",
            "ADD COLUMN state_changed_at TEXT",
            "ADD COLUMN state_reason TEXT",
        ):
            self._connection.execute(f"ALTER TABLE tsunade_experiences {statement}")
        # Until now an experience was only written when a user saved a verified
        # repair: each count was one attempt, and its last use a success.
        self._connection.execute(
            """UPDATE tsunade_experiences
            SET attempt_count=success_count+failure_count,
            last_success_at=CASE WHEN success_count>0 THEN last_used_at END"""
        )

    def _initialize(self) -> None:
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tsunade_incidents (
                incident_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                equipment_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                started_at TEXT NOT NULL,
                last_observed_at TEXT NOT NULL,
                ended_at TEXT,
                last_observation_id TEXT NOT NULL,
                message TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL,
                recurrence_count INTEGER NOT NULL,
                context_json TEXT NOT NULL,
                final_result TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS tsunade_active_capability
            ON tsunade_incidents(node_id, service_id, capability_id)
            WHERE ended_at IS NULL;
            CREATE TABLE IF NOT EXISTS tsunade_incident_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                observation_id TEXT,
                status TEXT,
                summary TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tsunade_events_incident
            ON tsunade_incident_events(incident_id, event_id);
            CREATE INDEX IF NOT EXISTS tsunade_events_kind
            ON tsunade_incident_events(kind);
            CREATE TABLE IF NOT EXISTS tsunade_capability_state (
                node_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                status TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                observation_id TEXT NOT NULL,
                PRIMARY KEY(node_id, service_id, capability_id)
            );
            CREATE TABLE IF NOT EXISTS tsunade_processed_observations (
                observation_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS tsunade_repairs (
                repair_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                target TEXT NOT NULL,
                risk TEXT NOT NULL,
                status TEXT NOT NULL,
                proposed_at TEXT NOT NULL,
                authorized_at TEXT,
                authorization_source TEXT,
                authorized_by TEXT,
                executed_at TEXT,
                verified_at TEXT,
                result TEXT
            );
            CREATE INDEX IF NOT EXISTS tsunade_repairs_incident
            ON tsunade_repairs(incident_id, proposed_at);
            CREATE TABLE IF NOT EXISTS tsunade_user_requests (
                request_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                origin TEXT NOT NULL,
                kind TEXT NOT NULL,
                context TEXT NOT NULL,
                question TEXT NOT NULL,
                choices_json TEXT NOT NULL,
                risk TEXT,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                deferred_until TEXT,
                answered_at TEXT,
                answer TEXT,
                answer_source TEXT,
                answered_by TEXT,
                action_reference TEXT
            );
            CREATE INDEX IF NOT EXISTS tsunade_user_requests_state
            ON tsunade_user_requests(state,created_at);
            CREATE INDEX IF NOT EXISTS tsunade_user_requests_incident
            ON tsunade_user_requests(incident_id,created_at);
            CREATE TABLE IF NOT EXISTS tsunade_experiences (
                experience_id TEXT PRIMARY KEY,
                signature TEXT NOT NULL UNIQUE,
                equipment_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                symptoms_json TEXT NOT NULL,
                context_json TEXT NOT NULL,
                observations_json TEXT NOT NULL,
                anomalies_json TEXT NOT NULL,
                validated_diagnostic TEXT NOT NULL,
                action_json TEXT NOT NULL,
                result TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL,
                success_count INTEGER NOT NULL,
                failure_count INTEGER NOT NULL,
                last_used_at TEXT NOT NULL,
                confidence REAL NOT NULL,
                confirmed_by TEXT NOT NULL,
                confirmation_source TEXT NOT NULL,
                incident_id TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tsunade_experiences_capability
            ON tsunade_experiences(equipment_id, capability_id, last_used_at);
            CREATE TABLE IF NOT EXISTS tsunade_accepted_log_signatures (
                source TEXT NOT NULL,
                signature TEXT NOT NULL,
                summary TEXT NOT NULL,
                accepted_at TEXT NOT NULL,
                PRIMARY KEY(source, signature)
            );
            """
        )
        repair_columns = {
            row[1]
            for row in self._connection.execute("PRAGMA table_info(tsunade_repairs)")
        }
        if "verification_deadline" not in repair_columns:
            # Additive migration: older rows keep the fixed verification delay.
            self._connection.execute(
                "ALTER TABLE tsunade_repairs ADD COLUMN verification_deadline TEXT"
            )
        if "experience_id" not in repair_columns:
            # The known repair an execution was counted against, if any.
            self._connection.execute(
                "ALTER TABLE tsunade_repairs ADD COLUMN experience_id TEXT"
            )
        self._migrate_experience_history()
        self.initialize_followups()
        self._connection.commit()
