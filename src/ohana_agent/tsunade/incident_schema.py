"""SQLite schema and migrations of the Tsunade control database."""

from __future__ import annotations


class TsunadeIncidentSchema:
    """SQLite schema and migrations of the Tsunade control database."""

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
            """
        )
        self.initialize_followups()
        self._connection.commit()
