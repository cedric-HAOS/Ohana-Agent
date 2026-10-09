"""Export durable client authorizations, without pending jobs or pairing requests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import yaml

ARCHIVE_PATH = "etc/ohana-agent/recovery/authorizations.json"
TABLES = {
    "jobs": ("distributed_worker_credentials",),
    "control": ("companion_credentials", "companion_push_tokens"),
}


def export_authorizations(configuration_path: Path, destination: Path) -> bool:
    """Take read transactions over configured databases and export selected tables."""
    if not configuration_path.is_file():
        return False
    configuration = yaml.safe_load(configuration_path.read_text(encoding="utf-8"))
    administration = configuration.get("administration", {})
    jobs = administration.get("jobs", {}).get(
        "database_path", "/var/lib/ohana-agent/distributed-jobs.db"
    )
    paths = {"jobs": jobs, "control": administration.get("database_path") or jobs}
    document: dict[str, object] = {"schema_version": 1, "tables": {}}
    tables = document["tables"]
    assert isinstance(tables, dict)
    for group, names in TABLES.items():
        connection = sqlite3.connect(
            Path(paths[group]).resolve().as_uri() + "?mode=ro", uri=True
        )
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            for name in names:
                if (
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,),
                    ).fetchone()
                    is None
                ):
                    continue
                cursor = connection.execute(f'SELECT * FROM "{name}"')
                tables[name] = {
                    "columns": [column[0] for column in cursor.description],
                    "rows": cursor.fetchall(),
                }
        finally:
            connection.close()
    destination.write_text(json.dumps(document), encoding="utf-8")
    destination.chmod(0o600)
    return True
