"""Security tests for job-bound direct HAOS log descriptors."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ohana_agent.jobs.log_sources import LogSourceBroker, read_infra_journal
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.plugins.backup.config import BackupConfig, BackupTarget


@pytest.mark.parametrize("line_count", [9999, 10000, 10001])
def test_journal_line_limit_is_explicit_without_byte_overflow(monkeypatch, line_count):
    lines = [f"line-{index}\n".encode() for index in range(line_count)]

    def run(command, **kwargs):
        assert command[command.index("--lines") + 1] == "10001"
        assert kwargs["timeout"] == 30
        return SimpleNamespace(returncode=0, stdout=b"".join(lines), stderr=b"")

    monkeypatch.setattr("ohana_agent.jobs.log_sources.subprocess.run", run)
    content, truncated = read_infra_journal(
        "2026-09-20T00:00:00+02:00", "2026-09-20T01:00:00+02:00", 4 * 1024 * 1024
    )
    assert truncated is (line_count > 10000)
    assert content.splitlines() == [line.decode().strip() for line in lines[-10000:]]


def test_journal_byte_limit_returns_complete_tail_lines(monkeypatch):
    monkeypatch.setattr(
        "ohana_agent.jobs.log_sources.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=b"first long line\nlast\n", stderr=b""
        ),
    )
    content, truncated = read_infra_journal(
        "2026-09-20T00:00:00+02:00", "2026-09-20T01:00:00+02:00", 9
    )
    assert truncated is True
    assert content == "last\n"


def test_log_source_secret_is_job_bound_and_never_persisted_in_parameters(
    tmp_path: Path,
) -> None:
    repository = DistributedJobRepository(tmp_path / "jobs.db")
    now = datetime.now(UTC)
    job_id = uuid4()
    try:
        repository.create(
            {
                "protocol_version": 1,
                "job_id": str(job_id),
                "type": "logs.health_check",
                "created_at": now.isoformat(),
                "parameters": {
                    "sources": ["ha-01"],
                    "window_started_at": (now - timedelta(hours=24)).isoformat(),
                    "window_ended_at": now.isoformat(),
                    "max_bytes_per_source": 2048,
                    "baseline": [],
                    "incident_id": None,
                },
                "timeout": 600,
            }
        )
        claimed = repository.claim(
            {
                "protocol_version": 1,
                "worker_id": "katsuyu-bubule",
                "supported_types": ["logs.health_check"],
            }
        ).job
        assert claimed is not None
        broker = LogSourceBroker(
            BackupConfig(
                targets=(
                    BackupTarget(
                        id="ha-01",
                        label="HA-01",
                        url="http://ha-01.ohana.lan:8123",
                        schedule="0 2 * * *",
                        token="home-assistant-secret",
                    ),
                )
            ),
            repository,
        )
        descriptor = broker.descriptor(
            str(job_id), "katsuyu-bubule", claimed.attempt, "ha-01"
        )

        assert descriptor["url"] == (
            "http://ha-01.ohana.lan:8123/api/hassio/"
            "core/logs/latest?lines=10000&no_colors=1"
        )
        assert descriptor["access_token"] == "home-assistant-secret"
        stored_parameters = repository.get(str(job_id)).parameters
        assert "home-assistant-secret" not in str(stored_parameters)
        with pytest.raises(ValueError, match="not authorized"):
            broker.descriptor(
                str(job_id), "katsuyu-bubule", claimed.attempt, "zwave-01"
            )
    finally:
        repository.close()


def test_infra_log_source_returns_only_a_bounded_job_authorized_journal(
    tmp_path: Path,
) -> None:
    repository = DistributedJobRepository(tmp_path / "jobs.db")
    now = datetime.now(UTC)
    job_id = uuid4()
    calls: list[tuple[str, str, int]] = []

    def read_journal(started_at: str, ended_at: str, max_bytes: int):
        calls.append((started_at, ended_at, max_bytes))
        return "2026-08-29T09:14:04+02:00 Ohana-Agent shutdown requested.\n", True

    try:
        repository.create(
            {
                "protocol_version": 1,
                "job_id": str(job_id),
                "type": "logs.health_check",
                "created_at": now.isoformat(),
                "parameters": {
                    "sources": ["infra-01"],
                    "window_started_at": (now - timedelta(hours=24)).isoformat(),
                    "window_ended_at": now.isoformat(),
                    "max_bytes_per_source": 2048,
                    "baseline": [],
                    "incident_id": None,
                },
                "timeout": 600,
            }
        )
        claimed = repository.claim(
            {
                "protocol_version": 1,
                "worker_id": "katsuyu-bubule",
                "supported_types": ["logs.health_check"],
            }
        ).job
        assert claimed is not None
        broker = LogSourceBroker(BackupConfig(), repository, read_journal)

        descriptor = broker.descriptor(
            str(job_id), "katsuyu-bubule", claimed.attempt, "infra-01"
        )

        assert descriptor == {
            "schema_version": 1,
            "source": "infra-01",
            "transport": "inline",
            "content": ("2026-08-29T09:14:04+02:00 Ohana-Agent shutdown requested.\n"),
            "truncated": True,
        }
        assert calls == [
            (
                (now - timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
                now.isoformat().replace("+00:00", "Z"),
                2048,
            )
        ]
        with pytest.raises(ValueError, match="not authorized"):
            broker.descriptor(str(job_id), "katsuyu-bubule", claimed.attempt, "ha-01")
    finally:
        repository.close()
