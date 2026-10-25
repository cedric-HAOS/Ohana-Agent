"""Phase 10: published archives are read again and compared with their record."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ohana_agent.plugins.backup.archive_integrity import ArchiveIntegrityReporter
from ohana_agent.plugins.backup.archive_verifier import ArchiveVerifier
from ohana_agent.plugins.backup.config import (
    BackupConfig,
    BackupTarget,
    InfraBackupConfig,
)
from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor

FAKE_RCLONE = r"""
import json, os, sys
root = os.environ["FAKE_RCLONE_ROOT"]
operation, remote = sys.argv[1], sys.argv[2]
path = os.path.join(root, remote.split("icloud:Ohana/Backups", 1)[1].lstrip("/"))
if os.environ.get("FAKE_RCLONE_DOWN"):
    sys.stderr.write("Invalid global session")
    sys.exit(1)
if operation == "lsjson":
    items = []
    for folder, _dirs, names in os.walk(path):
        for name in names:
            full = os.path.join(folder, name)
            items.append({
                "Path": os.path.relpath(full, path).replace(os.sep, "/"),
                "Name": name,
                "Size": os.path.getsize(full),
                "IsDir": False,
            })
    sys.stdout.write(json.dumps(items))
elif operation == "cat":
    limit = None
    if "--count" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--count") + 1])
    with open(path, "rb") as source:
        data = source.read() if limit is None else source.read(limit)
    sys.stdout.buffer.write(data)
else:
    sys.exit(2)
"""


def _wrapper(directory: Path) -> str:
    shim = directory / "fake_rclone.py"
    shim.write_text(FAKE_RCLONE, encoding="utf-8")
    if os.name == "nt":
        wrapper = directory / "rclone.cmd"
        wrapper.write_text(f'@"{sys.executable}" "{shim}" %*\r\n', encoding="utf-8")
    else:
        wrapper = directory / "rclone"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{shim}" "$@"\n')
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    return str(wrapper)


@pytest.fixture
def remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "remote"
    root.mkdir()
    monkeypatch.setenv("FAKE_RCLONE_ROOT", str(root))
    monkeypatch.delenv("FAKE_RCLONE_DOWN", raising=False)
    return root


@pytest.fixture
def config(tmp_path: Path, remote: Path) -> BackupConfig:
    return BackupConfig(
        targets=(
            BackupTarget(
                id="ha-01", label="HA-01", url="http://ha", schedule="0 2 * * 0"
            ),
        ),
        rclone_binary=_wrapper(tmp_path),
        rclone_config_path=str(tmp_path / "rclone.conf"),
        infra_01=InfraBackupConfig(enabled=True),
    )


def _infra_archive(
    remote: Path, backup_id: str, body: bytes, *, lie: bool = False
) -> None:
    folder = remote / "infra-01" / backup_id
    folder.mkdir(parents=True)
    (folder / f"{backup_id}.tar.age").write_bytes(body)
    manifest = {
        "archive": {
            "filename": f"{backup_id}.tar.age",
            "size_bytes": len(body),
            "sha256": "0" * 64 if lie else hashlib.sha256(body).hexdigest(),
        }
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _haos_archive(
    remote: Path, stamp: str, body: bytes, *, digest: str | None = None
) -> None:
    folder = remote / "ha-01" / "2026" / "10"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stamp}_abcd1234.tar").write_bytes(body)
    (folder / f"{stamp}_abcd1234.tar.sha256").write_text(
        f"{digest or hashlib.sha256(body).hexdigest()}  {stamp}_abcd1234.tar\n"
    )


AGE_BODY = b"age-encryption.org/v1\n-> X25519 abc\n" + os.urandom(3 * 1024 * 1024 + 17)
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _verifier(config: BackupConfig) -> ArchiveVerifier:
    return ArchiveVerifier(config, clock=lambda: NOW)


def test_targets_are_the_enabled_haos_targets_and_infra(config) -> None:
    assert _verifier(config).targets() == ["ha-01", "infra-01"]


def test_intact_infra_archive_is_verified_without_decrypting(config, remote) -> None:
    _infra_archive(remote, "20261024T020000Z", b"older")
    _infra_archive(remote, "20261025T030000Z", AGE_BODY)

    check = _verifier(config).verify("infra-01")

    assert check.outcome == "ok"
    assert check.backup_ref == "20261025T030000Z"
    assert check.size_bytes == len(AGE_BODY)
    assert check.actual_sha256 == hashlib.sha256(AGE_BODY).hexdigest()
    assert check.encrypted is True


def test_an_altered_infra_archive_is_a_hash_mismatch(config, remote) -> None:
    _infra_archive(remote, "20261025T030000Z", AGE_BODY, lie=True)

    check = _verifier(config).verify("infra-01")

    assert check.outcome == "hash_mismatch"
    assert check.actual_sha256 != check.expected_sha256


def test_an_archive_that_is_not_age_is_reported(config, remote) -> None:
    _infra_archive(remote, "20261025T030000Z", b"plain tar " * 100000)

    assert _verifier(config).verify("infra-01").outcome == "not_encrypted"


def test_a_truncated_archive_is_a_size_mismatch(config, remote) -> None:
    _infra_archive(remote, "20261025T030000Z", AGE_BODY)
    archive = remote / "infra-01" / "20261025T030000Z" / "20261025T030000Z.tar.age"
    archive.write_bytes(AGE_BODY[: len(AGE_BODY) // 2])

    check = _verifier(config).verify("infra-01")

    assert check.outcome == "size_mismatch"
    assert "attendus" in check.detail


def test_a_directory_without_manifest_is_not_a_complete_backup(config, remote) -> None:
    _infra_archive(remote, "20261024T020000Z", b"complete")
    partial = remote / "infra-01" / "20261025T030000Z"
    partial.mkdir()
    (partial / "20261025T030000Z.tar.age").write_bytes(b"half uploaded")

    assert _verifier(config).verify("infra-01").backup_ref == "20261024T020000Z"


def test_haos_archive_is_compared_with_its_sha256_file(config, remote) -> None:
    _haos_archive(remote, "20261018T000000Z", b"old")
    _haos_archive(remote, "20261025T000000Z", b"new haos tar" * 5000)

    check = _verifier(config).verify("ha-01")

    assert (check.outcome, check.backup_ref) == ("ok", "20261025T000000Z_abcd1234")
    assert check.encrypted is None


def test_haos_corruption_is_detected(config, remote) -> None:
    _haos_archive(remote, "20261025T000000Z", b"tar" * 1000, digest="f" * 64)

    assert _verifier(config).verify("ha-01").outcome == "hash_mismatch"


def test_no_published_backup_is_missing(config, remote) -> None:
    assert _verifier(config).verify("infra-01").outcome == "missing"
    assert _verifier(config).verify("ha-01").outcome == "missing"


def test_an_unreachable_remote_proves_nothing_about_the_archive(
    config, remote, monkeypatch
) -> None:
    _infra_archive(remote, "20261025T030000Z", AGE_BODY)
    monkeypatch.setenv("FAKE_RCLONE_DOWN", "1")

    check = _verifier(config).verify("infra-01")

    assert check.outcome == "unreadable"
    assert "session" in check.detail


class Sync:
    """Run the background pass in the calling thread."""

    def __init__(self, target, args, name, daemon):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)

    def is_alive(self):
        return False


def _reporter(config, monitor, clock):
    return ArchiveIntegrityReporter(
        ArchiveVerifier(config, clock=lambda: clock.wall),
        record=monitor.record_archive_check,
        last_check=monitor.last_archive_check,
        thread_factory=Sync,
        monotonic_clock=clock.read,
        now=lambda: clock.wall,
    )


class Clock:
    def __init__(self) -> None:
        self.mono = 0.0
        self.wall = datetime.now(UTC)

    def read(self) -> float:
        return self.mono

    def advance(self, **kwargs) -> None:
        delta = timedelta(**kwargs)
        self.mono += delta.total_seconds()
        self.wall += delta


def test_reporter_reads_a_new_archive_once_then_weekly(
    config, remote, tmp_path
) -> None:
    _infra_archive(remote, "20261025T030000Z", AGE_BODY)
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    clock = Clock()
    reporter = _reporter(config, monitor, clock)
    try:
        reporter.start()
        reporter.tick()
        assert monitor.last_archive_check("infra-01") is None  # first delay

        clock.advance(hours=1)
        reporter.tick()
        first = monitor.last_archive_check("infra-01")
        assert first["outcome"] == "ok"
        assert monitor.last_archive_check("ha-01")["outcome"] == "missing"

        clock.advance(days=2)
        reporter.tick()
        assert (
            monitor.last_archive_check("infra-01")["checked_at"] == first["checked_at"]
        )

        clock.advance(days=6)
        reporter.tick()
        assert (
            monitor.last_archive_check("infra-01")["checked_at"] != first["checked_at"]
        )
    finally:
        monitor.close()


def test_forced_request_reads_even_a_recently_verified_archive(
    config, remote, tmp_path
) -> None:
    _infra_archive(remote, "20261025T030000Z", AGE_BODY)
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    clock = Clock()
    reporter = _reporter(config, monitor, clock)
    try:
        assert reporter.request("infra-01") == ["infra-01"]
        first = monitor.last_archive_check("infra-01")
        clock.advance(minutes=5)
        assert reporter.request("infra-01") == ["infra-01"]
        assert (
            monitor.last_archive_check("infra-01")["checked_at"] != first["checked_at"]
        )
        with pytest.raises(ValueError, match="Unknown"):
            reporter.request("nowhere")
    finally:
        monitor.close()


def test_a_proven_alteration_is_urgent_and_unreadable_is_not(
    config, remote, tmp_path, monkeypatch
) -> None:
    _infra_archive(remote, "20261025T030000Z", AGE_BODY, lie=True)
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    clock = Clock()
    reporter = _reporter(config, monitor, clock)
    try:
        monitor.record_backup_success("infra-01", datetime.now(UTC))
        reporter.request("infra-01")
        summary = monitor.summary()
        altered = next(
            i for i in summary["watch"] if i["subject"] == "infra-01:integrity"
        )
        assert altered["urgent"] is True
        assert "altérée ou absente" in altered["title"]
        assert summary["conclusion"].startswith("Intervention à prévoir")

        monkeypatch.setenv("FAKE_RCLONE_DOWN", "1")
        reporter.request("infra-01")
        unreadable = next(
            i
            for i in monitor.summary()["watch"]
            if i["subject"] == "infra-01:integrity"
        )
        assert unreadable["urgent"] is False
        assert "illisible" in unreadable["title"]
    finally:
        monitor.close()


def test_an_intact_but_old_check_is_flagged_for_a_new_look(
    config, remote, tmp_path
) -> None:
    _infra_archive(remote, "20261025T030000Z", AGE_BODY)
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    clock = Clock()
    reporter = _reporter(config, monitor, clock)
    try:
        monitor.record_backup_success("infra-01", datetime.now(UTC))
        reporter.request("infra-01")
        assert all(
            i["subject"] != "infra-01:integrity" for i in monitor.summary()["watch"]
        )
        future = datetime.now(UTC) + timedelta(days=15)
        stale = next(
            i
            for i in monitor.summary(now=future)["watch"]
            if i["subject"] == "infra-01:integrity"
        )
        assert stale["urgent"] is False
        assert "non revérifiée" in stale["title"]
    finally:
        monitor.close()
