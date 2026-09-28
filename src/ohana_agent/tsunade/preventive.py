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
from pathlib import Path
from threading import RLock
from typing import Any

from ohana_agent.observation.observation import Observation
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

RULES: tuple[dict[str, str], ...] = (
    {
        "id": "disk_growth",
        "title": "Croissance du disque",
        "rule": (
            f"Maximum journalier de l'occupation disque sur {WINDOW_DAYS} jours : "
            f"au moins {DISK_MIN_DAYS} jours mesurés, pente d'au moins "
            f"{DISK_MIN_SLOPE} point par jour et au moins {DISK_MIN_RISES} "
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
        self._connection.commit()
        # Pending daily aggregates: written every FLUSH_INTERVAL, not per
        # sample, because INFRA-01 writes to a slow SD card every minute.
        self._days: dict[tuple[str, str, str], _Day] = {}
        self._last_flush: datetime | None = None
        self._agent_restarts: dict[str, int] = {}

    # Recording -----------------------------------------------------------

    def handle(self, event: Any) -> None:
        """Consume a HostHealthObserved event; never disturb the event bus."""
        try:
            self.record_host_health(event.observation)
        except Exception:  # noqa: BLE001 - the next sample records again.
            LOGGER.exception("Unable to record the preventive host samples")

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
            uptime = health.get("host_uptime_seconds")
            if isinstance(uptime, int | float) and uptime >= 0:
                self._record_boot(node, observed_at - timedelta(seconds=uptime))
            restarts = health.get("agent_restarts")
            if isinstance(restarts, int) and restarts >= 0:
                self._record_agent_restarts(node, observed_at, restarts)
            if (
                self._last_flush is None
                or observed_at - self._last_flush >= FLUSH_INTERVAL
                or any(key[0] != observed_at.date().isoformat() for key in self._days)
            ):
                self._flush(observed_at)

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
                """SELECT minimum, maximum, samples FROM tsunade_trend_daily
                WHERE day=? AND node_id=? AND metric=?""",
                key,
            ).fetchone()
            current = (
                _Day(row["minimum"], row["maximum"], value, row["samples"])
                if row
                else _Day(value, value, value, 0)
            )
            self._days[key] = current
        current.minimum = min(current.minimum, value)
        current.maximum = max(current.maximum, value)
        current.last = value
        current.samples += 1
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
                    samples, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(day, node_id, metric) DO UPDATE SET
                    minimum=excluded.minimum, maximum=excluded.maximum,
                    last_value=excluded.last_value, samples=excluded.samples,
                    updated_at=excluded.updated_at""",
                    (
                        *key,
                        day.minimum,
                        day.maximum,
                        day.last,
                        day.samples,
                        paris_iso(current),
                    ),
                )
                day.dirty = False
                written = True
            if key[0] != today:
                del self._days[key]
        cutoff = (current.date() - timedelta(days=90)).isoformat()
        self._connection.execute(
            "DELETE FROM tsunade_trend_daily WHERE day < ?", (cutoff,)
        )
        if written:
            self._connection.commit()
        self._last_flush = current

    # Evaluation ----------------------------------------------------------

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
            ]
            active_incidents = self._active_incidents()
        watch = [item for check in checks for item in check.pop("items")]
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
            "conclusion": conclusion,
            "text": _synthesis(headline, watch, conclusion),
            "checks": checks,
            "automatic_actions": False,
        }

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
            """SELECT day, node_id, maximum FROM tsunade_trend_daily
            WHERE metric='disk_percent' AND day >= ? AND day <= ?
            ORDER BY node_id, day""",
            (since, current.date().isoformat()),
        ).fetchall()
        series: dict[str, list[tuple[date, float]]] = {}
        for row in rows:
            series.setdefault(row["node_id"], []).append(
                (date.fromisoformat(row["day"]), float(row["maximum"]))
            )
        items: list[dict[str, Any]] = []
        nodes: list[dict[str, Any]] = []
        for node, points in series.items():
            evaluation = _disk_evaluation(points)
            nodes.append({"node_id": node, **evaluation})
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
    origin = points[0][0]
    xs = [(day - origin).days for day, _ in points]
    ys = [value for _, value in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    slope = (
        sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread
        if spread
        else 0.0
    )
    rises = sum(
        1
        for (_, before), (_, after) in zip(points, points[1:], strict=False)
        if after - before >= DISK_RISE_EPSILON
    )
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
    return f"{value:.1f}".replace(".", ",")


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
