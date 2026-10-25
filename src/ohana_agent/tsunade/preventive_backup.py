"""Phase 10: a backup is trusted only once someone restored it.

The Agent knows when each target was last backed up (the ``backup.run``
observations) and keeps the restoration tests the owner declares. This module
turns both into the preventive rule ``backup_restore``: a target never tested,
whose last test failed or is too old, is reported. Nothing is inferred: a
restoration is a real operation on a real machine, so only the owner declares
its outcome.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from ohana_agent.tsunade.local_time import paris_iso, to_paris

RESTORE_OUTCOMES = ("ok", "partial", "failed")
RESTORE_TEST_MAX_AGE_DAYS = 180
HISTORY_LIMIT = 20
RULE: dict[str, str] = {
    "id": "backup_restore",
    "title": "Restauration des sauvegardes",
    "rule": (
        "Une cible sauvegardée doit avoir été restaurée avec succès au moins "
        f"une fois, et au plus tard il y a {RESTORE_TEST_MAX_AGE_DAYS} jours. "
        "Un test partiel ou échoué reste signalé jusqu'à un nouveau test réussi. "
        "Seul l'utilisateur déclare le résultat d'une restauration."
    ),
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS tsunade_backup_runs (
    target TEXT PRIMARY KEY,
    last_success_at TEXT NOT NULL,
    successes INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS tsunade_restore_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    tested_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reference TEXT NOT NULL,
    note TEXT NOT NULL,
    declared_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tsunade_restore_tests_target
    ON tsunade_restore_tests (target, tested_at);
"""


def install(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def record_backup_success(
    connection: sqlite3.Connection, target: str, at: datetime
) -> None:
    connection.execute(
        """INSERT INTO tsunade_backup_runs (target, last_success_at)
        VALUES (?, ?)
        ON CONFLICT(target) DO UPDATE SET
            last_success_at = excluded.last_success_at,
            successes = successes + 1""",
        (target, paris_iso(at)),
    )
    connection.commit()


def declare_restore_test(
    connection: sqlite3.Connection,
    *,
    target: str,
    outcome: str,
    tested_at: datetime,
    declared_at: datetime,
    reference: str = "",
    note: str = "",
) -> dict[str, Any]:
    target = target.strip().lower()
    if not target or len(target) > 64:
        raise ValueError("target is required")
    if outcome not in RESTORE_OUTCOMES:
        raise ValueError("outcome must be ok, partial or failed")
    if to_paris(tested_at) > to_paris(declared_at) + timedelta(minutes=5):
        raise ValueError("tested_at cannot be in the future")
    if outcome != "ok" and not note.strip():
        raise ValueError("a partial or failed restoration needs a note")
    cursor = connection.execute(
        """INSERT INTO tsunade_restore_tests
        (target, tested_at, outcome, reference, note, declared_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (
            target,
            paris_iso(tested_at),
            outcome,
            reference.strip()[:200],
            note.strip()[:1000],
            paris_iso(declared_at),
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM tsunade_restore_tests WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _test(row)


def _test(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "target": row["target"],
        "tested_at": paris_iso(row["tested_at"]),
        "outcome": row["outcome"],
        "reference": row["reference"],
        "note": row["note"],
        "declared_at": paris_iso(row["declared_at"]),
    }


def targets(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """SELECT target FROM tsunade_backup_runs
        UNION SELECT target FROM tsunade_restore_tests ORDER BY target"""
    ).fetchall()
    return [row[0] for row in rows]


def posture(connection: sqlite3.Connection, current: datetime) -> list[dict[str, Any]]:
    """One entry per target: backup, last restoration test and its verdict."""
    current = to_paris(current)
    result = []
    for target in targets(connection):
        run = connection.execute(
            "SELECT last_success_at, successes FROM tsunade_backup_runs "
            "WHERE target = ?",
            (target,),
        ).fetchone()
        tests = connection.execute(
            """SELECT * FROM tsunade_restore_tests WHERE target = ?
            ORDER BY tested_at DESC, id DESC LIMIT ?""",
            (target, HISTORY_LIMIT),
        ).fetchall()
        last = _test(tests[0]) if tests else None
        last_ok = next((_test(t) for t in tests if t["outcome"] == "ok"), None)
        age_days = (
            (current - to_paris(datetime.fromisoformat(last_ok["tested_at"]))).days
            if last_ok
            else None
        )
        if last is None:
            state, text = "never_tested", "jamais testée en restauration"
        elif last["outcome"] != "ok":
            label = "partielle" if last["outcome"] == "partial" else "échouée"
            state, text = "last_failed", f"dernière restauration {label}"
        elif age_days is not None and age_days > RESTORE_TEST_MAX_AGE_DAYS:
            state, text = "stale", f"dernier test réussi il y a {age_days} jours"
        else:
            state = "verified"
            text = f"restaurée avec succès il y a {age_days} jour(s)"
        result.append(
            {
                "target": target,
                "state": state,
                "text": text,
                "last_backup_success_at": (
                    paris_iso(run["last_success_at"]) if run else None
                ),
                "backup_successes": run["successes"] if run else 0,
                "last_test": last,
                "last_verified_at": last_ok["tested_at"] if last_ok else None,
                "history": [_test(t) for t in tests],
            }
        )
    return result


def restore_readiness(connection: sqlite3.Connection, current: datetime) -> dict:
    """Preventive check: the targets whose restoration is not demonstrated."""
    entries = posture(connection, current)
    nodes, items = [], []
    for entry in entries:
        target, state = entry["target"], entry["state"]
        nodes.append(
            {
                "node_id": target,
                "state": "ok" if state == "verified" else "watch",
                "summary": f"{target.upper()} : {entry['text']}",
            }
        )
        if state == "verified":
            continue
        last = entry["last_test"]
        if state == "never_tested":
            detail = (
                "Aucune restauration de cette sauvegarde n'a été déclarée : "
                "elle n'est pas démontrée restaurable."
            )
        elif state == "last_failed":
            detail = f"Test du {last['tested_at'][:10]} : {last['note']}"
        else:
            detail = (
                f"Dernier test réussi le {entry['last_verified_at'][:10]}, "
                f"plus ancien que {RESTORE_TEST_MAX_AGE_DAYS} jours."
            )
        items.append(
            {
                "rule": RULE["id"],
                "node_id": target,
                "equipment_id": target,
                "subject": target,
                "title": f"{target.upper()} : sauvegarde {entry['text']}",
                "detail": detail,
                "since": (last or {}).get("tested_at")
                or entry["last_backup_success_at"],
                "urgent": state == "last_failed",
                "evidence": {
                    "state": state,
                    "last_backup_success_at": entry["last_backup_success_at"],
                    "last_verified_at": entry["last_verified_at"],
                },
            }
        )
    if items:
        check_state = "watch"
    elif not nodes:
        check_state = "insufficient_data"
    else:
        check_state = "ok"
    return {**RULE, "state": check_state, "nodes": nodes, "items": items}
