"""Phase 4: a few explainable drifts, reported before they become incidents.

Tsunade keeps one compact row per day and metric from the host health it
already receives, remembers host boots and automatic Agent restarts, and reads
its own incident history for repeated network interruptions. The rules are
plain thresholds on that data: no AI, no Katsuyu, and nothing here ever opens
an incident or proposes a repair.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import median
from threading import RLock
from typing import Any

from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus
from ohana_agent.tsunade import preventive_rules
from ohana_agent.tsunade.local_time import paris_iso, paris_now, to_paris

LOGGER = logging.getLogger(__name__)

WINDOW_DAYS = 7
DISK_MIN_DAYS = 4
DISK_MIN_SLOPE = 0.5
DISK_MIN_RISES = 3
DISK_RISE_EPSILON = 0.1
DISK_HIGH_PERCENT = 70.0
DISK_FULL_PERCENT = 90.0
DISK_HORIZON_DAYS = 30
DISK_URGENT_DAYS = 7
REBOOT_THRESHOLD = 2
INTERRUPTION_THRESHOLD = 3
NETWORK_CAPABILITY = "network.reachable"
BOOT_TOLERANCE = timedelta(minutes=3)
FLUSH_INTERVAL = timedelta(minutes=15)
MAX_MUTE_DAYS = 90
# Drifts an open incident already follows: listed apart, not as a new alert.
COVERED_BY_INCIDENT = {
    "network_interruptions": ("network.reachable",),
    "response_time": ("dns.resolve", "mqtt.roundtrip", "network.reachable"),
}

RULES: tuple[dict[str, str], ...] = (
    {
        "id": "disk_growth",
        "title": "Croissance du disque",
        "rule": (
            f"Maximum journalier de l'occupation disque sur {WINDOW_DAYS} jours : "
            f"au moins {DISK_MIN_DAYS} jours mesurés, hausse médiane d'au moins "
            f"{str(DISK_MIN_SLOPE).replace('.', ',')} point par jour et au moins "
            f"{DISK_MIN_RISES} "
            f"hausses d'un jour sur l'autre ; signalé si l'occupation atteint "
            f"{DISK_HIGH_PERCENT:.0f} % ou si {DISK_FULL_PERCENT:.0f} % serait "
            f"atteint sous {DISK_HORIZON_DAYS} jours."
        ),
    },
    {
        "id": "repeated_reboots",
        "title": "Redémarrages répétés",
        "rule": (
            f"Au moins {REBOOT_THRESHOLD} démarrages de l'hôte ou redémarrages "
            f"automatiques de l'Agent (systemd) sur {WINDOW_DAYS} jours. "
            "Un redémarrage demandé (mise à jour, systemctl restart) "
            "n'est pas compté."
        ),
    },
    {
        "id": "network_interruptions",
        "title": "Interruptions réseau répétées",
        "rule": (
            f"Au moins {INTERRUPTION_THRESHOLD} incidents {NETWORK_CAPABILITY} "
            f"ouverts pour le même équipement sur {WINDOW_DAYS} jours."
        ),
    },
)


@dataclass(slots=True)
class _Day:
    minimum: float
    maximum: float
    last: float
    samples: int
    total: float = 0.0
    dirty: bool = True


class TsunadePreventiveMonitor:
    """Record the few daily values the rules need and evaluate them on demand."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tsunade_trend_daily (
                day TEXT NOT NULL,
                node_id TEXT NOT NULL,
                metric TEXT NOT NULL,
                minimum REAL NOT NULL,
                maximum REAL NOT NULL,
                last_value REAL NOT NULL,
                samples INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (day, node_id, metric)
            );
            CREATE TABLE IF NOT EXISTS tsunade_trend_events (
                node_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                PRIMARY KEY (node_id, kind, occurred_at)
            );
            """
        )
        columns = {
            row[1]
            for row in self._connection.execute(
                "PRAGMA table_info(tsunade_trend_daily)"
            )
        }
        if "source" not in columns:
            # Lot 3: live rows come from the Agent, rebuilt ones from Home
            # Assistant statistics through Katsuyu.
            self._connection.execute(
                "ALTER TABLE tsunade_trend_daily "
                "ADD COLUMN source TEXT NOT NULL DEFAULT 'agent'"
            )
        if "total" not in columns:
            # Daily sum: response times are compared on their daily mean.
            self._connection.execute(
                "ALTER TABLE tsunade_trend_daily "
                "ADD COLUMN total REAL NOT NULL DEFAULT 0"
            )
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS tsunade_preventive_mutes (
                rule TEXT NOT NULL,
                subject TEXT NOT NULL,
                title TEXT NOT NULL,
                muted_until TEXT NOT NULL,
                muted_at TEXT NOT NULL,
                PRIMARY KEY (rule, subject)
            )"""
        )
        self._connection.commit()
        # Pending daily aggregates: written every FLUSH_INTERVAL, not per
        # sample, because INFRA-01 writes to a slow SD card every minute.
        self._days: dict[tuple[str, str, str], _Day] = {}
        self._last_flush: datetime | None = None
        self._purged_on: str | None = None
        self._agent_restarts: dict[str, int] = {}

    # Recording -----------------------------------------------------------

    def handle(self, event: Any) -> None:
        """Consume a HostHealthObserved event; never disturb the event bus."""
        try:
            self.record_host_health(event.observation)
        except Exception:  # noqa: BLE001 - the next sample records again.
            LOGGER.exception("Unable to record the preventive host samples")

    def handle_observation(self, event: Any) -> None:
        """Consume ObservationPublished for response times; never raise."""
        try:
            self.record_observation(event.observation)
        except Exception:  # noqa: BLE001 - the next observation records again.
            LOGGER.exception("Unable to record the preventive response time")

    def record_observation(self, observation: Observation) -> None:
        """Daily response time of successful DNS, MQTT and network checks."""
        latency = observation.latency_ms
        if (
            observation.capability not in preventive_rules.LATENCY_CAPABILITIES
            or observation.status is not ObservationStatus.HEALTHY
            or not isinstance(latency, int | float)
            or latency < 0
        ):
            return
        metric = f"latency_ms:{observation.capability}:{observation.service}"
        self.record_metric(
            str(observation.node), metric, float(latency), observation.timestamp
        )

    def record_metric(self, node: str, metric: str, value: float, at: datetime) -> None:
        observed_at = to_paris(at)
        with self._lock:
            self._accumulate(observed_at, node, metric, float(value))
            self._maybe_flush(observed_at)

    def record_snapshot(
        self, node: str, kind: str, at: datetime, detail: dict[str, Any]
    ) -> None:
        """Keep the day's latest detail (one row per node, kind and day)."""
        day = to_paris(at).date().isoformat()
        with self._lock:
            self._connection.execute(
                """INSERT INTO tsunade_trend_events
                (node_id, kind, occurred_at, detail_json) VALUES (?, ?, ?, ?)
                ON CONFLICT(node_id, kind, occurred_at)
                DO UPDATE SET detail_json=excluded.detail_json""",
                (node, kind, day, json.dumps(detail)),
            )
            cutoff = (to_paris(at).date() - timedelta(days=90)).isoformat()
            self._connection.execute(
                "DELETE FROM tsunade_trend_events WHERE kind=? AND occurred_at < ?",
                (kind, cutoff),
            )
            self._connection.commit()

    def _maybe_flush(self, observed_at: datetime) -> None:
        if (
            self._last_flush is None
            or observed_at - self._last_flush >= FLUSH_INTERVAL
            or any(key[0] != observed_at.date().isoformat() for key in self._days)
        ):
            self._flush(observed_at)

    def record_host_health(self, observation: Observation) -> None:
        health = observation.metadata.get("host_health")
        if not isinstance(health, dict):
            return
        node = str(observation.node)
        observed_at = to_paris(observation.timestamp)
        with self._lock:
            disk = health.get("disk_percent")
            if isinstance(disk, int | float):
                self._accumulate(observed_at, node, "disk_percent", float(disk))
            vision = health.get("vision")
            for metric, value in (
                ("memory_percent", health.get("memory_percent")),
                ("swap_percent", health.get("swap_percent")),
                ("ohana_data_bytes", health.get("ohana_data_bytes")),
                (
                    "vision_db_bytes",
                    vision.get("database_bytes") if isinstance(vision, dict) else None,
                ),
            ):
                if isinstance(value, int | float) and not isinstance(value, bool):
                    self._accumulate(observed_at, node, metric, float(value))
            uptime = health.get("host_uptime_seconds")
            if isinstance(uptime, int | float) and uptime >= 0:
                self._record_boot(node, observed_at - timedelta(seconds=uptime))
            restarts = health.get("agent_restarts")
            if isinstance(restarts, int) and restarts >= 0:
                self._record_agent_restarts(node, observed_at, restarts)
            self._maybe_flush(observed_at)

    def missing_days(
        self, node: str, metric: str, *, now: datetime | None = None
    ) -> list[str]:
        """Past days of the rule window without any daily value."""
        current = to_paris(now) if now is not None else paris_now()
        wanted = [
            (current.date() - timedelta(days=offset)).isoformat()
            for offset in range(WINDOW_DAYS - 1, 0, -1)
        ]
        with self._lock:
            present = {
                row[0]
                for row in self._connection.execute(
                    """SELECT day FROM tsunade_trend_daily
                    WHERE node_id=? AND metric=? AND day >= ?""",
                    (node, metric, wanted[0]),
                )
            }
        return [day for day in wanted if day not in present]

    def record_backfill(
        self,
        node: str,
        metric: str,
        days: list[dict[str, Any]],
        *,
        source: str,
        now: datetime | None = None,
    ) -> int:
        """Store rebuilt past days; a day the Agent measured itself is kept."""
        current = to_paris(now) if now is not None else paris_now()
        today = current.date().isoformat()
        inserted = 0
        with self._lock:
            for value in days:
                day = str(value["day"])
                if day >= today:
                    # Today is still being measured live.
                    continue
                cursor = self._connection.execute(
                    """INSERT OR IGNORE INTO tsunade_trend_daily
                    (day, node_id, metric, minimum, maximum, last_value, samples,
                    updated_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        day,
                        node,
                        metric,
                        float(value["minimum"]),
                        float(value["maximum"]),
                        float(value["last"]),
                        int(value["hours"]),
                        paris_iso(current),
                        source,
                    ),
                )
                inserted += cursor.rowcount
            self._connection.commit()
        return inserted

    def flush(self) -> None:
        with self._lock:
            self._flush(paris_now())

    def close(self) -> None:
        with self._lock:
            self._flush(paris_now())
            self._connection.close()

    def _accumulate(
        self, observed_at: datetime, node: str, metric: str, value: float
    ) -> None:
        key = (observed_at.date().isoformat(), node, metric)
        current = self._days.get(key)
        if current is None:
            row = self._connection.execute(
                """SELECT minimum, maximum, samples, total FROM tsunade_trend_daily
                WHERE day=? AND node_id=? AND metric=?""",
                key,
            ).fetchone()
            current = (
                _Day(
                    row["minimum"], row["maximum"], value, row["samples"], row["total"]
                )
                if row
                else _Day(value, value, value, 0)
            )
            self._days[key] = current
        current.minimum = min(current.minimum, value)
        current.maximum = max(current.maximum, value)
        current.last = value
        current.samples += 1
        current.total += value
        current.dirty = True

    def _record_boot(self, node: str, booted_at: datetime) -> None:
        booted_at = booted_at.replace(second=0, microsecond=0)
        latest = self._connection.execute(
            """SELECT occurred_at FROM tsunade_trend_events
            WHERE node_id=? AND kind='host_boot'
            ORDER BY julianday(occurred_at) DESC LIMIT 1""",
            (node,),
        ).fetchone()
        # /proc/uptime drifts a little against the wall clock: one boot, one row.
        if (
            latest
            and abs(datetime.fromisoformat(latest[0]) - booted_at) <= BOOT_TOLERANCE
        ):
            return
        self._event(node, "host_boot", booted_at, {})

    def _record_agent_restarts(
        self, node: str, observed_at: datetime, restarts: int
    ) -> None:
        previous = self._agent_restarts.get(node)
        if previous is None:
            row = self._connection.execute(
                """SELECT detail_json FROM tsunade_trend_events
                WHERE node_id=? AND kind='agent_restart_counter'""",
                (node,),
            ).fetchone()
            previous = json.loads(row[0])["value"] if row else None
        if previous is not None and restarts > previous:
            self._event(
                node,
                "agent_restart",
                observed_at.replace(microsecond=0),
                {"count": restarts - previous},
            )
        if previous != restarts:
            # systemd resets NRestarts when the unit is reloaded: only a rise
            # is an automatic restart, a lower value is the new baseline.
            self._connection.execute(
                """INSERT INTO tsunade_trend_events
                (node_id, kind, occurred_at, detail_json)
                VALUES (?, 'agent_restart_counter', '', ?)
                ON CONFLICT(node_id, kind, occurred_at)
                DO UPDATE SET detail_json=excluded.detail_json""",
                (node, json.dumps({"value": restarts})),
            )
            self._connection.commit()
        self._agent_restarts[node] = restarts

    def _event(
        self, node: str, kind: str, occurred_at: datetime, detail: dict[str, Any]
    ) -> None:
        self._connection.execute(
            """INSERT OR IGNORE INTO tsunade_trend_events
            (node_id, kind, occurred_at, detail_json) VALUES (?, ?, ?, ?)""",
            (node, kind, paris_iso(occurred_at), json.dumps(detail)),
        )
        self._connection.commit()

    def _flush(self, current: datetime) -> None:
        today = current.date().isoformat()
        written = False
        for key, day in list(self._days.items()):
            if day.dirty:
                self._connection.execute(
                    """INSERT INTO tsunade_trend_daily
                    (day, node_id, metric, minimum, maximum, last_value,
                    samples, updated_at, total) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(day, node_id, metric) DO UPDATE SET
                    minimum=excluded.minimum, maximum=excluded.maximum,
                    last_value=excluded.last_value, samples=excluded.samples,
                    updated_at=excluded.updated_at, total=excluded.total""",
                    (
                        *key,
                        day.minimum,
                        day.maximum,
                        day.last,
                        day.samples,
                        paris_iso(current),
                        day.total,
                    ),
                )
                day.dirty = False
                written = True
            if key[0] != today:
                del self._days[key]
        if self._purged_on != today:
            cutoff = (current.date() - timedelta(days=90)).isoformat()
            self._connection.execute(
                "DELETE FROM tsunade_trend_daily WHERE day < ?", (cutoff,)
            )
            self._purged_on = today
            written = True
        # Any DML opened a transaction: leaving it open would lock the whole
        # control database for the incident repository.
        if written:
            self._connection.commit()
        self._last_flush = current

    # Evaluation ----------------------------------------------------------

    def storage_growth(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Phase 5: daily maximum size of the Agent and Vision databases."""
        current = to_paris(now) if now is not None else paris_now()
        since = (current.date() - timedelta(days=WINDOW_DAYS - 1)).isoformat()
        with self._lock:
            self._flush(current)
            rows = self._connection.execute(
                """SELECT metric, day, maximum FROM tsunade_trend_daily
                WHERE metric IN ('ohana_data_bytes', 'vision_db_bytes')
                AND day >= ? ORDER BY metric, day""",
                (since,),
            ).fetchall()
        series: dict[str, list[tuple[str, float]]] = {}
        for row in rows:
            series.setdefault(row["metric"], []).append((row["day"], row["maximum"]))
        growth: dict[str, Any] = {"window_days": WINDOW_DAYS}
        for metric, key in (
            ("ohana_data_bytes", "agent"),
            ("vision_db_bytes", "vision"),
        ):
            points = series.get(metric, [])
            if not points:
                growth[key] = None
                continue
            first, last = (date.fromisoformat(points[i][0]) for i in (0, -1))
            days = max((last - first).days, 1)
            growth[key] = {
                "days": len(points),
                "first_day": points[0][0],
                "first_bytes": int(points[0][1]),
                "latest_bytes": int(points[-1][1]),
                "bytes_per_day": (
                    int((points[-1][1] - points[0][1]) / days)
                    if len(points) > 1
                    else None
                ),
            }
        return growth

    def summary(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Evaluate every rule and phrase the short synthesis."""
        current = to_paris(now) if now is not None else paris_now()
        with self._lock:
            self._flush(current)
            checks = [
                self._disk_growth(current),
                self._repeated_reboots(current),
                self._network_interruptions(current),
                preventive_rules.memory_growth(self._connection, current),
                preventive_rules.response_time(self._connection, current),
                preventive_rules.log_errors_growth(self._connection, current),
                preventive_rules.ha_unavailable_entities(self._connection, current),
            ]
            active_incidents = self._active_incidents()
            mutes = self._active_mutes(current)
            followed = self._followed_by_incidents()
        found = [item for check in checks for item in check.pop("items")]
        for item in found:
            item.setdefault("subject", str(item.get("equipment_id")))
        # Fewer useless alerts: a drift the user muted, or one an open incident
        # already follows, is kept apart from the list to watch.
        muted = [item for item in found if (item["rule"], item["subject"]) in mutes]
        covered = [
            item
            for item in found
            if item not in muted
            and any(
                (item["equipment_id"], capability) in followed
                for capability in COVERED_BY_INCIDENT.get(item["rule"], ())
            )
        ]
        watch = [item for item in found if item not in muted and item not in covered]
        correlations = preventive_rules.correlate(watch)
        for item in muted:
            item["muted_until"] = mutes[(item["rule"], item["subject"])]
        urgent = [item for item in watch if item.get("urgent")]
        if active_incidents:
            headline = (
                f"{active_incidents} incident en cours, suivi par Tsunade."
                if active_incidents == 1
                else f"{active_incidents} incidents en cours, suivis par Tsunade."
            )
        else:
            headline = "Konoha est stable."
        conclusion = (
            "Intervention à prévoir : " + " ; ".join(i["title"] for i in urgent) + "."
            if urgent
            else "Aucune intervention nécessaire."
        )
        return {
            "schema_version": 1,
            "generated_at": paris_iso(current),
            "window_days": WINDOW_DAYS,
            "status": "watch" if watch else "stable",
            "headline": headline,
            "watch": watch,
            "correlations": correlations,
            "muted": muted,
            "followed_by_incident": covered,
            "conclusion": conclusion,
            "text": _synthesis(headline, watch, conclusion),
            "checks": checks,
            "automatic_actions": False,
        }

    # Fewer useless alerts ------------------------------------------------

    def mute(
        self,
        rule: str,
        subject: str,
        *,
        days: int,
        title: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Hide one drift from the watch list for ``days``; it stays visible."""
        known = {item["id"] for item in RULES} | {
            item["id"] for item in preventive_rules.RULES
        }
        if rule not in known:
            raise ValueError(f"unknown preventive rule: {rule}")
        if not subject.strip() or len(subject) > 400:
            raise ValueError("a preventive subject is required")
        if not 1 <= days <= MAX_MUTE_DAYS:
            raise ValueError(f"days must be between 1 and {MAX_MUTE_DAYS}")
        current = to_paris(now) if now is not None else paris_now()
        until = current + timedelta(days=days)
        with self._lock:
            self._connection.execute(
                """INSERT INTO tsunade_preventive_mutes
                (rule, subject, title, muted_until, muted_at) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(rule, subject) DO UPDATE SET title=excluded.title,
                muted_until=excluded.muted_until, muted_at=excluded.muted_at""",
                (rule, subject, title[:300], paris_iso(until), paris_iso(current)),
            )
            self._connection.commit()
        return {"rule": rule, "subject": subject, "muted_until": paris_iso(until)}

    def unmute(self, rule: str, subject: str) -> dict[str, Any]:
        with self._lock:
            removed = self._connection.execute(
                "DELETE FROM tsunade_preventive_mutes WHERE rule=? AND subject=?",
                (rule, subject),
            ).rowcount
            self._connection.commit()
        if not removed:
            raise LookupError("this drift is not muted")
        return {"rule": rule, "subject": subject, "muted_until": None}

    def _active_mutes(self, current: datetime) -> dict[tuple[str, str], str]:
        return {
            (row[0], row[1]): paris_iso(row[2])
            for row in self._connection.execute(
                "SELECT rule, subject, muted_until FROM tsunade_preventive_mutes"
            )
            if datetime.fromisoformat(row[2]) > current
        }

    def _followed_by_incidents(self) -> set[tuple[str, str]]:
        try:
            return {
                (row[0], row[1])
                for row in self._connection.execute(
                    """SELECT equipment_id, capability_id FROM tsunade_incidents
                    WHERE ended_at IS NULL"""
                )
            }
        except sqlite3.OperationalError:
            return set()

    def _active_incidents(self) -> int:
        try:
            return int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM tsunade_incidents WHERE ended_at IS NULL"
                ).fetchone()[0]
            )
        except sqlite3.OperationalError:
            return 0

    def _disk_growth(self, current: datetime) -> dict[str, Any]:
        since = (current.date() - timedelta(days=WINDOW_DAYS - 1)).isoformat()
        rows = self._connection.execute(
            """SELECT day, node_id, maximum, source FROM tsunade_trend_daily
            WHERE metric='disk_percent' AND day >= ? AND day <= ?
            ORDER BY node_id, day""",
            (since, current.date().isoformat()),
        ).fetchall()
        series: dict[str, list[tuple[date, float]]] = {}
        rebuilt: dict[str, int] = {}
        for row in rows:
            series.setdefault(row["node_id"], []).append(
                (date.fromisoformat(row["day"]), float(row["maximum"]))
            )
            if row["source"] != "agent":
                rebuilt[row["node_id"]] = rebuilt.get(row["node_id"], 0) + 1
        items: list[dict[str, Any]] = []
        nodes: list[dict[str, Any]] = []
        for node, points in series.items():
            evaluation = _disk_evaluation(points)
            nodes.append(
                {
                    "node_id": node,
                    **evaluation,
                    "rebuilt_days": rebuilt.get(node, 0),
                }
            )
            if evaluation["state"] == "watch":
                items.append(_disk_item(node, points, evaluation))
        state = _check_state(items, nodes)
        return {
            **_rule("disk_growth"),
            "state": state,
            "nodes": nodes,
            "items": items,
        }

    def _repeated_reboots(self, current: datetime) -> dict[str, Any]:
        since = current - timedelta(days=WINDOW_DAYS)
        rows = self._connection.execute(
            """SELECT node_id, kind, occurred_at, detail_json
            FROM tsunade_trend_events
            WHERE kind IN ('host_boot', 'agent_restart')
            AND julianday(occurred_at) >= julianday(?)
            ORDER BY julianday(occurred_at)""",
            (paris_iso(since),),
        ).fetchall()
        tracked = {
            row[0]
            for row in self._connection.execute(
                "SELECT DISTINCT node_id FROM tsunade_trend_events"
            )
        }
        events: dict[str, list[dict[str, Any]]] = {node: [] for node in tracked}
        for row in rows:
            count = int(json.loads(row["detail_json"]).get("count", 1))
            events.setdefault(row["node_id"], []).append(
                {
                    "kind": row["kind"],
                    "occurred_at": paris_iso(row["occurred_at"]),
                    "count": count,
                }
            )
        items: list[dict[str, Any]] = []
        nodes: list[dict[str, Any]] = []
        for node, occurrences in sorted(events.items()):
            total = sum(event["count"] for event in occurrences)
            state = "watch" if total >= REBOOT_THRESHOLD else "ok"
            nodes.append(
                {"node_id": node, "state": state, "count": total, "events": occurrences}
            )
            if state == "watch":
                boots = sum(e["count"] for e in occurrences if e["kind"] == "host_boot")
                restarts = total - boots
                parts = []
                if boots:
                    parts.append(f"{boots} démarrage{'s' if boots > 1 else ''}")
                if restarts:
                    parts.append(
                        f"{restarts} redémarrage{'s' if restarts > 1 else ''} "
                        "automatique" + ("s" if restarts > 1 else "") + " de l'Agent"
                    )
                items.append(
                    {
                        "rule": "repeated_reboots",
                        "node_id": node,
                        "equipment_id": node,
                        "title": (
                            f"{node.upper()} : {' et '.join(parts)} "
                            f"en {WINDOW_DAYS} jours"
                        ),
                        "detail": "Derniers : "
                        + ", ".join(
                            _short_time(e["occurred_at"]) for e in occurrences[-5:]
                        )
                        + ".",
                        "since": occurrences[0]["occurred_at"],
                        "evidence": {"events": occurrences},
                        "urgent": False,
                    }
                )
        return {
            **_rule("repeated_reboots"),
            "state": _check_state(items, nodes),
            "nodes": nodes,
            "items": items,
        }

    def _network_interruptions(self, current: datetime) -> dict[str, Any]:
        since = current - timedelta(days=WINDOW_DAYS)
        try:
            rows = self._connection.execute(
                """SELECT equipment_id, node_id, started_at, ended_at
                FROM tsunade_incidents WHERE capability_id=?
                AND julianday(started_at) >= julianday(?)
                ORDER BY julianday(started_at)""",
                (NETWORK_CAPABILITY, paris_iso(since)),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        interruptions: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            started = to_paris(datetime.fromisoformat(row["started_at"]))
            ended = (
                to_paris(datetime.fromisoformat(row["ended_at"]))
                if row["ended_at"]
                else None
            )
            interruptions.setdefault(row["equipment_id"], []).append(
                {
                    "started_at": paris_iso(started),
                    "ended_at": paris_iso(ended) if ended else None,
                    "duration_seconds": (
                        int((ended - started).total_seconds()) if ended else None
                    ),
                }
            )
        items: list[dict[str, Any]] = []
        nodes: list[dict[str, Any]] = []
        for equipment, occurrences in sorted(interruptions.items()):
            state = "watch" if len(occurrences) >= INTERRUPTION_THRESHOLD else "ok"
            nodes.append(
                {"node_id": equipment, "state": state, "count": len(occurrences)}
            )
            if state != "watch":
                continue
            durations = [
                o["duration_seconds"]
                for o in occurrences
                if o["duration_seconds"] is not None
            ]
            longest = max(durations) if durations else None
            ongoing = sum(1 for o in occurrences if o["ended_at"] is None)
            detail = f"Dernière le {_short_time(occurrences[-1]['started_at'])}"
            if longest is not None:
                detail += f", la plus longue {_duration(longest)}"
            if ongoing:
                detail += ", une toujours en cours"
            items.append(
                {
                    "rule": "network_interruptions",
                    "node_id": equipment,
                    "equipment_id": equipment,
                    "title": (
                        f"{equipment.upper()} : {len(occurrences)} interruptions "
                        f"réseau en {WINDOW_DAYS} jours"
                    ),
                    "detail": detail + ".",
                    "since": occurrences[0]["started_at"],
                    "evidence": {"interruptions": occurrences},
                    "urgent": False,
                }
            )
        return {
            **_rule("network_interruptions"),
            "state": "watch" if items else "ok",
            "nodes": nodes,
            "items": items,
        }


def _rule(rule_id: str) -> dict[str, str]:
    return next(dict(rule) for rule in RULES if rule["id"] == rule_id)


def _check_state(items: list[Any], nodes: list[dict[str, Any]]) -> str:
    if items:
        return "watch"
    if not nodes or all(n["state"] == "insufficient_data" for n in nodes):
        return "insufficient_data"
    return "ok"


def _disk_evaluation(points: list[tuple[date, float]]) -> dict[str, Any]:
    latest = points[-1][1]
    evaluation: dict[str, Any] = {
        "days": len(points),
        "first_percent": points[0][1],
        "latest_percent": latest,
    }
    if len(points) < DISK_MIN_DAYS:
        return {**evaluation, "state": "insufficient_data"}
    # Median of the day-over-day changes: one apt upgrade or one large file
    # is a single jump and does not make a trend; a missing day is spread.
    deltas = [
        (after - before) / max((next_day - day).days, 1)
        for (day, before), (next_day, after) in zip(points, points[1:], strict=False)
    ]
    slope = median(deltas)
    rises = sum(1 for delta in deltas if delta >= DISK_RISE_EPSILON)
    days_to_full = max((DISK_FULL_PERCENT - latest) / slope, 0.0) if slope > 0 else None
    watch = (
        slope >= DISK_MIN_SLOPE
        and rises >= DISK_MIN_RISES
        and (
            latest >= DISK_HIGH_PERCENT
            or (days_to_full is not None and days_to_full <= DISK_HORIZON_DAYS)
        )
    )
    return {
        **evaluation,
        "state": "watch" if watch else "ok",
        "slope_points_per_day": round(slope, 2),
        "rises": rises,
        "days_to_full": round(days_to_full, 1) if days_to_full is not None else None,
    }


def _disk_item(
    node: str, points: list[tuple[date, float]], evaluation: dict[str, Any]
) -> dict[str, Any]:
    days_to_full = evaluation["days_to_full"]
    detail = (
        f"{_percent(evaluation['first_percent'])} → "
        f"{_percent(evaluation['latest_percent'])} "
        f"(+{_decimal(evaluation['slope_points_per_day'])} point/jour)"
    )
    if days_to_full is not None and days_to_full <= DISK_HORIZON_DAYS:
        detail += (
            f", {DISK_FULL_PERCENT:.0f} % atteint dans environ "
            f"{max(round(days_to_full), 1)} jours à ce rythme"
        )
    return {
        "rule": "disk_growth",
        "node_id": node,
        "equipment_id": node,
        "title": (
            f"{node.upper()} : espace disque en hausse depuis {len(points)} jours"
        ),
        "detail": detail + ".",
        "since": points[0][0].isoformat(),
        "evidence": {
            "daily_maximum": [
                {"day": day.isoformat(), "percent": value} for day, value in points
            ],
            **{
                key: evaluation[key]
                for key in ("slope_points_per_day", "rises", "days_to_full")
            },
        },
        "urgent": days_to_full is not None and days_to_full <= DISK_URGENT_DAYS,
    }


def _synthesis(headline: str, watch: list[dict[str, Any]], conclusion: str) -> str:
    lines = [headline]
    if watch:
        lines += ["", "À surveiller :"]
        lines += [f"- {item['title']}." for item in watch]
    lines += ["", conclusion]
    return "\n".join(lines)


def _decimal(value: float) -> str:
    # Half up, like Intl.NumberFormat in Vision: 1.15 reads 1,2 on both sides.
    rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return str(rounded).replace(".", ",")


def _percent(value: float) -> str:
    return f"{_decimal(value)} %"


def _short_time(value: str) -> str:
    return to_paris(datetime.fromisoformat(value)).strftime("%d/%m %H:%M")


def _duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d}"
