"""Phase 10: verify a published backup archive without trusting its creation.

The Agent re-reads the latest archive of each target from the remote and
compares it with what was recorded when it was published: size and SHA-256
(the manifest for INFRA-01, the ``.sha256`` file for HAOS). The archive is
streamed through ``rclone cat`` in bounded chunks: nothing is written to the
microSD card, nothing is decrypted, and no secret is read.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from ohana_agent.plugins.backup.config import BackupConfig

AGE_HEADER = b"age-encryption.org/v1"
BACKUP_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z")
SHA256_LINE = re.compile(r"^([0-9a-f]{64})(?:\s|$)")
CHUNK_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 1800.0
OUTCOMES = (
    "ok",
    "missing",
    "size_mismatch",
    "hash_mismatch",
    "not_encrypted",
    "unreadable",
)
# An unreadable remote says nothing about the archive: the iCloud session
# check reports it. Every other failure is a proven problem with the archive.
INCONCLUSIVE = {"unreadable"}


class RcloneReadError(RuntimeError):
    """rclone could not list or read the remote."""


@dataclass(frozen=True, slots=True)
class ArchiveCheck:
    target: str
    backup_ref: str
    outcome: str
    checked_at: datetime
    size_bytes: int | None = None
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    encrypted: bool | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Candidate:
    target: str
    backup_ref: str
    archive_path: str
    expected_size: int | None
    expected_sha256: str
    must_be_age: bool


class RcloneReader(Protocol):
    def list_files(self, remote_path: str) -> list[dict[str, Any]]: ...

    def read_small(self, remote_path: str, limit: int = 65536) -> bytes: ...

    def stream(self, remote_path: str, *, timeout: float) -> Iterator[bytes]: ...


class RcloneCliReader:
    """Read-only rclone operations: ``lsjson``, ``cat``."""

    def __init__(self, config: BackupConfig) -> None:
        self._config = config

    def list_files(self, remote_path: str) -> list[dict[str, Any]]:
        result = subprocess.run(
            self._command("lsjson", remote_path) + ["-R", "--files-only"],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        if result.returncode != 0:
            raise RcloneReadError(result.stderr[:300])
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as error:
            raise RcloneReadError("rclone returned invalid JSON.") from error
        if not isinstance(payload, list):
            raise RcloneReadError("rclone returned an unexpected listing.")
        return [item for item in payload if isinstance(item, dict)]

    def read_small(self, remote_path: str, limit: int = 65536) -> bytes:
        result = subprocess.run(
            self._command("cat", remote_path) + ["--count", str(limit)],
            capture_output=True,
            check=False,
            timeout=300,
        )
        if result.returncode != 0:
            raise RcloneReadError(result.stderr[:300].decode(errors="replace"))
        return result.stdout

    def stream(self, remote_path: str, *, timeout: float) -> Iterator[bytes]:
        deadline = time.monotonic() + timeout
        process = subprocess.Popen(
            self._command("cat", remote_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdout is not None
        try:
            while chunk := process.stdout.read(CHUNK_BYTES):
                if time.monotonic() > deadline:
                    raise RcloneReadError("The archive read exceeded its time limit.")
                yield chunk
            if process.wait(timeout=60) != 0:
                assert process.stderr is not None
                raise RcloneReadError(process.stderr.read(300).decode(errors="replace"))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def _command(self, operation: str, remote_path: str) -> list[str]:
        return [
            self._config.rclone_binary,
            operation,
            remote_path,
            "--config",
            self._config.rclone_config_path,
            "--log-level",
            "ERROR",
        ]


class ArchiveVerifier:
    """Compare the latest published archive of a target with its record."""

    def __init__(
        self,
        config: BackupConfig,
        reader: RcloneReader | None = None,
        *,
        clock: Any = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.config = config
        self._reader = reader or RcloneCliReader(config)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout = timeout_seconds

    def targets(self) -> list[str]:
        found = [target.id for target in self.config.targets if target.enabled]
        if self.config.infra_01.enabled:
            found.append("infra-01")
        return found

    def verify(
        self, target: str, *, skip: Callable[[str], bool] | None = None
    ) -> ArchiveCheck | None:
        """Read the latest archive; ``skip(backup_ref)`` may spare the download."""
        now = self._clock()
        try:
            candidate = self.latest(target)
        except RcloneReadError as error:
            return ArchiveCheck(target, "", "unreadable", now, detail=str(error))
        if candidate is None:
            return ArchiveCheck(
                target, "", "missing", now, detail="Aucune sauvegarde publiée."
            )
        if skip is not None and skip(candidate.backup_ref):
            return None
        return self._check(candidate, now)

    def latest(self, target: str) -> Candidate | None:
        remote = f"{self.config.rclone_remote}/{target}"
        files = self._reader.list_files(remote)
        if target == "infra-01":
            return self._latest_infra(target, remote, files)
        return self._latest_haos(target, remote, files)

    def _latest_infra(
        self, target: str, remote: str, files: list[dict[str, Any]]
    ) -> Candidate | None:
        complete = sorted(
            parts[0]
            for item in files
            if (parts := str(item.get("Path", "")).split("/"))
            and len(parts) == 2
            and parts[1] == "manifest.json"
            and BACKUP_ID.fullmatch(parts[0])
        )
        if not complete:
            return None
        backup_id = complete[-1]
        try:
            manifest = json.loads(
                self._reader.read_small(f"{remote}/{backup_id}/manifest.json")
            )
            archive = manifest["archive"]
            filename = str(archive["filename"])
            expected = str(archive["sha256"])
            size = int(archive["size_bytes"])
        except (ValueError, KeyError, TypeError) as error:
            raise RcloneReadError("Le manifeste est illisible.") from error
        return Candidate(
            target, backup_id, f"{remote}/{backup_id}/{filename}", size, expected, True
        )

    def _latest_haos(
        self, target: str, remote: str, files: list[dict[str, Any]]
    ) -> Candidate | None:
        paths = {str(item.get("Path", "")): item for item in files}
        archives = sorted(
            path
            for path in paths
            if path.endswith(".tar") and f"{path}.sha256" in paths
        )
        if not archives:
            return None
        # Names start with the UTC stamp, so the last name is the latest backup.
        path = max(archives, key=lambda value: value.rsplit("/", 1)[-1])
        digest = self._reader.read_small(f"{remote}/{path}.sha256").decode(
            errors="replace"
        )
        match = SHA256_LINE.match(digest.strip().lower())
        if match is None:
            raise RcloneReadError("Le fichier .sha256 est illisible.")
        return Candidate(
            target,
            path.rsplit("/", 1)[-1].removesuffix(".tar"),
            f"{remote}/{path}",
            None,
            match.group(1),
            False,
        )

    def _check(self, candidate: Candidate, now: datetime) -> ArchiveCheck:
        remote_size: int | None = None
        try:
            listing = self._reader.list_files(candidate.archive_path.rsplit("/", 1)[0])
            name = candidate.archive_path.rsplit("/", 1)[-1]
            entry = next((i for i in listing if i.get("Name") == name), None)
            if entry is None:
                return self._result(
                    candidate, now, "missing", detail="L'archive est introuvable."
                )
            remote_size = int(entry.get("Size", -1))
            if candidate.expected_size is not None and (
                remote_size != candidate.expected_size
            ):
                return self._result(
                    candidate,
                    now,
                    "size_mismatch",
                    size=remote_size,
                    detail=(
                        f"Taille distante {remote_size} octets, "
                        f"{candidate.expected_size} attendus."
                    ),
                )
            digest = hashlib.sha256()
            total = 0
            first = b""
            for chunk in self._reader.stream(
                candidate.archive_path, timeout=self._timeout
            ):
                if not first:
                    first = chunk[:64]
                digest.update(chunk)
                total += len(chunk)
        except (RcloneReadError, OSError, subprocess.SubprocessError) as error:
            return self._result(
                candidate, now, "unreadable", size=remote_size, detail=str(error)[:300]
            )
        actual = digest.hexdigest()
        encrypted = first.startswith(AGE_HEADER) if candidate.must_be_age else None
        outcome, detail = "ok", ""
        if total != remote_size:
            outcome, detail = (
                "size_mismatch",
                (f"{total} octets lus, {remote_size} annoncés par le remote."),
            )
        elif actual != candidate.expected_sha256:
            outcome, detail = (
                "hash_mismatch",
                ("L'empreinte SHA-256 diffère de celle enregistrée à la publication."),
            )
        elif encrypted is False:
            outcome, detail = (
                "not_encrypted",
                ("L'archive ne commence pas par l'en-tête age attendu."),
            )
        return self._result(
            candidate,
            now,
            outcome,
            size=total,
            actual=actual,
            encrypted=encrypted,
            detail=detail,
        )

    @staticmethod
    def _result(
        candidate: Candidate,
        now: datetime,
        outcome: str,
        *,
        size: int | None = None,
        actual: str | None = None,
        encrypted: bool | None = None,
        detail: str = "",
    ) -> ArchiveCheck:
        return ArchiveCheck(
            candidate.target,
            candidate.backup_ref,
            outcome,
            now,
            size_bytes=size,
            expected_sha256=candidate.expected_sha256,
            actual_sha256=actual,
            encrypted=encrypted,
            detail=detail,
        )
