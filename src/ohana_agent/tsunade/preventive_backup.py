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
INTEGRITY_MAX_AGE_DAYS = 14
INTEGRITY_HISTORY_DAYS = 90
INCONCLUSIVE = {"unreadable"}
RULE: dict[str, str] = {
    "id": "backup_restore",
    "title": "Restauration des sauvegardes",
    "rule": (
        "Une cible sauvegardée doit avoir été restaurée avec succès au moins "
        f"une fois, et au plus tard il y a {RESTORE_TEST_MAX_AGE_DAYS} jours. "
        "Un test partiel ou échoué reste signalé jusqu'à un nouveau test réussi. "
        "L'archive la plus récente est relue depuis le remote (taille, SHA-256, "
        "en-tête age) ; une archive altérée ou absente est urgente, un contrôle "
        f"de plus de {INTEGRITY_MAX_AGE_DAYS} jours est signalé. "
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
CREATE TABLE IF NOT EXISTS tsunade_archive_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    backup_ref TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    size_bytes INTEGER,
    expected_sha256 TEXT,
    actual_sha256 TEXT,
    encrypted INTEGER,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tsunade_archive_checks_target
    ON tsunade_archive_checks (target, checked_at);
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


def record_archive_check(
    connection: sqlite3.Connection,
    *,
    target: str,
    backup_ref: str,
    checked_at: datetime,
    outcome: str,
    size_bytes: int | None = None,
    expected_sha256: str | None = None,
    actual_sha256: str | None = None,
    encrypted: bool | None = None,
    detail: str = "",
) -> None:
    connection.execute(
        """INSERT INTO tsunade_archive_checks
        (target, backup_ref, checked_at, outcome, size_bytes, expected_sha256,
         actual_sha256, encrypted, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            target,
            backup_ref,
            paris_iso(checked_at),
            outcome,
            size_bytes,
            expected_sha256,
            actual_sha256,
            None if encrypted is None else int(encrypted),
            detail[:300],
        ),
    )
    cutoff = paris_iso(to_paris(checked_at) - timedelta(days=INTEGRITY_HISTORY_DAYS))
    connection.execute(
        "DELETE FROM tsunade_archive_checks WHERE checked_at < ?", (cutoff,)
    )
    connection.commit()


def _check(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "backup_ref": row["backup_ref"],
        "checked_at": paris_iso(row["checked_at"]),
        "outcome": row["outcome"],
        "size_bytes": row["size_bytes"],
        "encrypted": None if row["encrypted"] is None else bool(row["encrypted"]),
        "detail": row["detail"],
    }


def last_archive_check(
    connection: sqlite3.Connection, target: str
) -> dict[str, Any] | None:
    row = connection.execute(
        """SELECT * FROM tsunade_archive_checks WHERE target = ?
        ORDER BY checked_at DESC, id DESC LIMIT 1""",
        (target,),
    ).fetchone()
    return _check(row) if row else None


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
        UNION SELECT target FROM tsunade_restore_tests
        UNION SELECT target FROM tsunade_archive_checks ORDER BY target"""
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
                "integrity": last_archive_check(connection, target),
                "last_test": last,
                "last_verified_at": last_ok["tested_at"] if last_ok else None,
                "history": [_test(t) for t in tests],
            }
        )
    return result


def _integrity_item(entry: dict[str, Any], current: datetime) -> dict | None:
    """A proven archive problem is urgent; a stale check only needs a look."""
    target, check = entry["target"], entry["integrity"]
    if check is None:
        return None
    age = (current - to_paris(datetime.fromisoformat(check["checked_at"]))).days
    if check["outcome"] == "ok":
        if age <= INTEGRITY_MAX_AGE_DAYS:
            return None
        title = f"{target.upper()} : intégrité de l'archive non revérifiée"
        detail = f"Dernier contrôle réussi il y a {age} jours."
        urgent = False
    elif check["outcome"] in INCONCLUSIVE:
        title = f"{target.upper()} : archive illisible depuis le remote"
        detail = (
            f"Le contrôle du {check['checked_at'][:10]} n'a pas pu lire l'archive : "
            f"{check['detail']}"
        )
        urgent = False
    else:
        title = f"{target.upper()} : archive sauvegardée altérée ou absente"
        detail = (
            f"Contrôle du {check['checked_at'][:10]} "
            f"({check['backup_ref']}) : {check['detail']}"
        )
        urgent = True
    return {
        "rule": RULE["id"],
        "node_id": target,
        "equipment_id": target,
        "subject": f"{target}:integrity",
        "title": title,
        "detail": detail,
        "since": check["checked_at"],
        "urgent": urgent,
        "evidence": {
            "backup_ref": check["backup_ref"],
            "outcome": check["outcome"],
            "checked_at": check["checked_at"],
        },
    }


def restore_readiness(connection: sqlite3.Connection, current: datetime) -> dict:
    """Preventive check: restorations not demonstrated, archives not intact."""
    current = to_paris(current)
    entries = posture(connection, current)
    nodes, items = [], []
    for entry in entries:
        target, state = entry["target"], entry["state"]
        integrity = _integrity_item(entry, current)
        nodes.append(
            {
                "node_id": target,
                "state": "ok" if state == "verified" and integrity is None else "watch",
                "summary": f"{target.upper()} : {entry['text']}",
            }
        )
        if integrity is not None:
            items.append(integrity)
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
