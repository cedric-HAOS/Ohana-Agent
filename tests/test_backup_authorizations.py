import json
import sqlite3

import pytest

from ohana_agent.plugins.backup.authorizations import export_authorizations


def test_export_preserves_credentials_without_pending_jobs(tmp_path):
    database = tmp_path / "agent.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TABLE distributed_worker_credentials"
            "(worker_id TEXT, token_sha256 TEXT);"
            "INSERT INTO distributed_worker_credentials VALUES"
            "('bubule','worker-hash');"
            "CREATE TABLE companion_credentials(device_id TEXT, token_sha256 TEXT);"
            "INSERT INTO companion_credentials VALUES ('phone','companion-hash');"
            "CREATE TABLE companion_push_tokens(device_id TEXT, device_token TEXT);"
            "INSERT INTO companion_push_tokens VALUES ('phone','push-token');"
            "CREATE TABLE distributed_jobs(job_id TEXT);"
            "INSERT INTO distributed_jobs VALUES ('pending-job');"
        )
    config = tmp_path / "shikamaru.yaml"
    config.write_text(
        json.dumps({"administration": {"jobs": {"database_path": str(database)}}})
    )
    destination = tmp_path / "authorizations.json"
    assert export_authorizations(config, destination)
    document = json.loads(destination.read_text())
    assert set(document["tables"]) == {
        "distributed_worker_credentials",
        "companion_credentials",
        "companion_push_tokens",
    }
    assert document["tables"]["distributed_worker_credentials"]["rows"] == [
        ["bubule", "worker-hash"]
    ]
    assert document["tables"]["companion_credentials"]["rows"] == [
        ["phone", "companion-hash"]
    ]
    assert "pending-job" not in destination.read_text()


def test_export_does_not_silently_ignore_missing_database(tmp_path):
    config = tmp_path / "shikamaru.yaml"
    config.write_text(
        json.dumps(
            {
                "administration": {
                    "jobs": {"database_path": str(tmp_path / "missing.db")}
                }
            }
        )
    )
    with pytest.raises(sqlite3.OperationalError):
        export_authorizations(config, tmp_path / "authorizations.json")
