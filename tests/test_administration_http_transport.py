"""Transport-level guarantees of the aiohttp administration listeners."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ohana_agent.api.http import AdministrationHTTPServer
from ohana_agent.api.service import AdministrationService
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository

JOB_ID = "11111111-1111-4111-8111-111111111111"
WORKER_HEADERS = {
    "Authorization": "Bearer katsuyu-secret",
    "X-Ohana-Worker-Id": "katsuyu-bubule",
    "X-Ohana-Attempt": "1",
}


class RecordingBackupTransfer:
    def __init__(self, source: bytes = b"", *, fail_after: int | None = None) -> None:
        self.source = source
        self.fail_after = fail_after
        self.received: list[tuple[str, str, int, int, str]] = []

    @contextmanager
    def open_source(self, _job_id: str, _worker_id: str, _attempt: int) -> Iterator:
        def stream(output) -> None:
            for offset in range(0, len(self.source), 64 * 1024):
                if self.fail_after is not None and offset >= self.fail_after:
                    raise OSError("source disappeared")
                output.write(self.source[offset : offset + 64 * 1024])

        yield stream

    def receive_artifact(
        self,
        job_id: str,
        worker_id: str,
        attempt: int,
        stream,
        *,
        size_bytes: int,
        expected_sha256: str,
    ) -> dict[str, object]:
        digest = hashlib.sha256()
        received = 0
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
            received += len(chunk)
        self.received.append(
            (job_id, worker_id, attempt, received, expected_sha256),
        )
        return {"size_bytes": received, "sha256": digest.hexdigest()}


def _server(
    tmp_path: Path,
    transfer: RecordingBackupTransfer | None = None,
    **options: object,
) -> AdministrationHTTPServer:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text("nodes: []\n", encoding="utf-8")
    return AdministrationHTTPServer(
        service=AdministrationService(
            infrastructure_repository=InfrastructureConfigurationRepository(
                infrastructure_path
            ),
            backup_transfer=transfer,
        ),
        token="tsunade-secret",
        worker_token="katsuyu-secret",
        port=0,
        **options,
    )


@contextmanager
def _running(server: AdministrationHTTPServer) -> Iterator[str]:
    server.start()
    try:
        assert server.address is not None
        host, port = server.address
        scheme = "https" if server.tls_certificate_file is not None else "http"
        yield f"{scheme}://{host}:{port}"
    finally:
        server.stop()


def test_backup_source_streams_a_large_archive_in_order(tmp_path: Path) -> None:
    source = os.urandom(3 * 1024 * 1024 + 17)
    server = _server(tmp_path, RecordingBackupTransfer(source), worker_only=True)

    with _running(server) as base_url:
        with urlopen(
            Request(f"{base_url}/v1/jobs/{JOB_ID}/input", headers=WORKER_HEADERS),
            timeout=5,
        ) as response:
            body = response.read()
            content_type = response.headers["Content-Type"]
            server_header = response.headers["Server"]

    assert hashlib.sha256(body).digest() == hashlib.sha256(source).digest()
    assert content_type == "application/x-tar"
    assert server_header == "Ohana-Agent-Administration/1"


def test_backup_source_failure_mid_stream_truncates_the_transfer(
    tmp_path: Path,
) -> None:
    transfer = RecordingBackupTransfer(os.urandom(2 * 1024 * 1024), fail_after=1024**2)
    server = _server(tmp_path, transfer, worker_only=True)

    with _running(server) as base_url:
        with pytest.raises((IncompleteRead, ConnectionError, URLError)):  # noqa: PT012
            with urlopen(
                Request(f"{base_url}/v1/jobs/{JOB_ID}/input", headers=WORKER_HEADERS),
                timeout=5,
            ) as response:
                response.read()


def test_backup_artifact_upload_streams_the_declared_body(tmp_path: Path) -> None:
    artifact = os.urandom(2 * 1024 * 1024 + 3)
    sha256 = hashlib.sha256(artifact).hexdigest()
    transfer = RecordingBackupTransfer()
    server = _server(tmp_path, transfer, worker_only=True)

    with _running(server) as base_url:
        with urlopen(
            Request(
                f"{base_url}/v1/jobs/{JOB_ID}/artifact",
                data=artifact,
                headers={
                    **WORKER_HEADERS,
                    "Content-Type": "application/octet-stream",
                    "X-Ohana-SHA256": sha256.upper(),
                },
                method="POST",
            ),
            timeout=5,
        ) as response:
            receipt = json.loads(response.read())

    assert receipt == {"size_bytes": len(artifact), "sha256": sha256}
    assert transfer.received == [
        (JOB_ID, "katsuyu-bubule", 1, len(artifact), sha256),
    ]


def test_worker_transfer_requires_a_positive_attempt(tmp_path: Path) -> None:
    server = _server(tmp_path, RecordingBackupTransfer(b"x"), worker_only=True)

    with _running(server) as base_url:
        with pytest.raises(HTTPError) as error:
            urlopen(
                Request(
                    f"{base_url}/v1/jobs/{JOB_ID}/input",
                    headers={**WORKER_HEADERS, "X-Ohana-Attempt": "zero"},
                ),
                timeout=5,
            )
        detail = json.loads(error.value.read())

    assert error.value.code == 400
    assert detail == {"detail": "Invalid job attempt"}


def test_companion_listener_does_not_accept_administration_writes(
    tmp_path: Path,
) -> None:
    server = _server(tmp_path, companion_only=True)

    with _running(server) as base_url:
        with pytest.raises(HTTPError) as error:
            urlopen(
                Request(
                    f"{base_url}/v1/infrastructure",
                    data=b"{}",
                    headers={
                        "Authorization": "Bearer tsunade-secret",
                        "Content-Type": "application/json",
                    },
                    method="PUT",
                ),
                timeout=5,
            )
        detail = json.loads(error.value.read())

    assert error.value.code == 404
    assert detail == {"detail": "Companion endpoint not found"}


def test_unsupported_methods_are_rejected(tmp_path: Path) -> None:
    server = _server(tmp_path)

    with _running(server) as base_url:
        with pytest.raises(HTTPError) as error:
            urlopen(
                Request(f"{base_url}/v1/infrastructure", method="DELETE"),
                timeout=5,
            )

    assert error.value.code == 501


def test_start_raises_when_the_port_is_taken(tmp_path: Path) -> None:
    first = _server(tmp_path)

    with _running(first):
        _, port = first.address
        second = AdministrationHTTPServer(
            service=first.service,
            token="tsunade-secret",
            port=port,
        )
        with pytest.raises(OSError):
            second.start()

    assert not second.running


def test_tls_listener_serves_https(tmp_path: Path) -> None:
    certificate_path, key_path = _self_signed_certificate(tmp_path)
    server = _server(
        tmp_path,
        worker_only=True,
        tls_certificate_file=certificate_path,
        tls_private_key_file=key_path,
    )
    context = ssl.create_default_context(cafile=str(certificate_path))

    with _running(server) as base_url:
        with pytest.raises(HTTPError) as error:
            urlopen(f"{base_url}/v1/jobs/unknown/route", timeout=5, context=context)

    assert base_url.startswith("https://")
    assert error.value.code == 404


def _self_signed_certificate(directory: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    certificate_path = directory / "listener.crt"
    key_path = directory / "listener.key"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, key_path
