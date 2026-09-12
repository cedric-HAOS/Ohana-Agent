"""Authenticated loopback HTTP API for Agent administration."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import ssl
from collections.abc import Callable
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

from pydantic import ValidationError

from ohana_agent.api.service import AdministrationService
from ohana_agent.companions.repository import (
    CompanionConflictError,
)
from ohana_agent.host.dhcp import DHCPConfigurationError
from ohana_agent.host.network import (
    NetworkAdministrationError,
)
from ohana_agent.jobs.repository import (
    DistributedJobConflictError,
)
from ohana_agent.plugins.backup.coordinator import BackupExecutionError
from ohana_agent.tsunade.expertise import (
    TsunadeExpertiseConflictError,
)

LOGGER = logging.getLogger(__name__)
MAXIMUM_REQUEST_BYTES = 1024 * 1024


class _BoundedRequestStream:
    """Expose exactly one declared HTTP request body and then return EOF."""

    def __init__(self, stream: object, size_bytes: int) -> None:
        self.stream = stream
        self.remaining = size_bytes

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        requested = self.remaining if size < 0 else min(size, self.remaining)
        chunk = self.stream.read(requested)
        self.remaining -= len(chunk)
        return chunk


class AdministrationHTTPServer:
    """Run the administration API in a dedicated loopback thread."""

    def __init__(
        self,
        *,
        service: AdministrationService,
        token: str,
        worker_token: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
        worker_only: bool = False,
        companion_only: bool = False,
        tls_certificate_file: Path | None = None,
        tls_private_key_file: Path | None = None,
    ) -> None:
        normalized_token = token.strip()

        if not normalized_token:
            raise ValueError("Administration token cannot be empty.")

        self.service = service
        self.token = normalized_token
        self.worker_token = worker_token.strip() if worker_token else None
        if self.worker_token and hmac.compare_digest(self.worker_token, self.token):
            raise ValueError("Worker and administration tokens must be different.")
        self.host = host
        self.port = port
        if worker_only and companion_only:
            raise ValueError("A listener cannot be worker-only and companion-only")
        if (tls_certificate_file is None) != (tls_private_key_file is None):
            raise ValueError(
                "TLS certificate and private key must be configured together"
            )
        self.worker_only = worker_only
        self.companion_only = companion_only
        self.tls_certificate_file = tls_certificate_file
        self.tls_private_key_file = tls_private_key_file
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def running(self) -> bool:
        """Return whether the administration server thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def address(self) -> tuple[str, int] | None:
        """Return the effective listening address."""
        if self._server is None:
            return None

        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        """Start the HTTP server once."""
        if self.running:
            return

        handler_class = self._handler_class()
        server = ThreadingHTTPServer(
            (self.host, self.port),
            handler_class,
        )
        if self.tls_certificate_file is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            try:
                context.load_cert_chain(
                    certfile=self.tls_certificate_file,
                    keyfile=self.tls_private_key_file,
                )
                server.socket = context.wrap_socket(server.socket, server_side=True)
            except Exception:
                server.server_close()
                raise
        self._server = server
        self._thread = Thread(
            target=self._server.serve_forever,
            name=(
                "ohana-agent-worker-https"
                if self.worker_only
                else "ohana-agent-companion-https"
                if self.companion_only
                else "ohana-agent-administration"
            ),
            daemon=True,
        )
        self._thread.start()
        scheme = "https" if self.tls_certificate_file is not None else "http"
        role = (
            "Katsuyu worker API"
            if self.worker_only
            else "Companion API"
            if self.companion_only
            else "Administration API"
        )
        LOGGER.info("%s listening on %s://%s:%s", role, scheme, *self.address)

    def stop(self) -> None:
        """Stop the HTTP server and release its socket."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

        if self._thread is not None:
            self._thread.join(timeout=5)

        self._server = None
        self._thread = None

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        service = self.service
        expected_token = self.token
        expected_worker_token = self.worker_token
        worker_only = self.worker_only
        companion_only = self.companion_only

        class AdministrationRequestHandler(BaseHTTPRequestHandler):
            """Handle one administration request."""

            server_version = "Ohana-Agent-Administration/1"

            def do_GET(self) -> None:  # noqa: N802
                """Handle administration reads."""
                path = self.path.split("?", 1)[0]
                if worker_only:
                    input_suffix = "/input"
                    log_source_marker = "/log-source/"
                    if path.startswith("/v1/jobs/") and path.endswith(input_suffix):
                        job_id = path[len("/v1/jobs/") : -len(input_suffix)]
                        if job_id and "/" not in job_id:
                            self._download_backup_source(job_id)
                        else:
                            self._write_error(
                                HTTPStatus.NOT_FOUND, "Worker endpoint not found"
                            )
                    elif path.startswith("/v1/jobs/") and log_source_marker in path:
                        remainder = path[len("/v1/jobs/") :]
                        job_id, separator, source_id = remainder.partition(
                            log_source_marker
                        )
                        if separator and job_id and source_id and "/" not in source_id:
                            identity = self._worker_transfer_identity()
                            if identity is not None:
                                worker_id, attempt = identity
                                self._execute(
                                    lambda: service.read_log_source(
                                        job_id,
                                        worker_id,
                                        attempt,
                                        source_id,
                                    )
                                )
                        else:
                            self._write_error(
                                HTTPStatus.NOT_FOUND, "Worker endpoint not found"
                            )
                    elif path == "/v1/jobs/workers/trust":
                        self._execute(service.read_worker_trust)
                    else:
                        self._write_error(
                            HTTPStatus.NOT_FOUND,
                            "Worker endpoint not found",
                        )
                    return
                if companion_only:
                    if path == "/v1/pairings/companions/trust":
                        if service.companion_ca_sha256 is None:
                            self._write_error(
                                HTTPStatus.NOT_FOUND,
                                "Companion trust is unavailable",
                            )
                        else:
                            self._write_json(
                                HTTPStatus.OK,
                                {
                                    "schema_version": 1,
                                    "tls_ca_sha256": service.companion_ca_sha256,
                                    "tls_ca_certificate_pem": (
                                        service.companion_ca_certificate_pem
                                    ),
                                },
                            )
                        return
                    identity = self._companion_identity()
                    if identity is None:
                        return
                    routes: dict[str, Callable[[], object]] = {
                        "/v1/incidents/summary": service.read_companion_summary,
                        "/v1/incidents/requests": service.read_companion_requests,
                        "/v1/incidents/requests/all": partial(
                            service.read_companion_requests, "all"
                        ),
                        "/v1/incidents/activity": service.read_companion_activity,
                    }
                    operation = routes.get(path)
                    if operation is None:
                        self._write_error(
                            HTTPStatus.NOT_FOUND, "Companion endpoint not found"
                        )
                    else:
                        self._execute(operation)
                    return
                if not self._authorized(expected_token, "administration"):
                    return

                routes: dict[str, Callable[[], object]] = {
                    "/v1/capabilities": service.capabilities,
                    "/v1/infrastructure": service.read_infrastructure,
                    "/v1/dhcp": service.read_dhcp,
                    "/v1/plugins": service.list_plugins,
                    "/v1/system/network": service.read_network,
                    "/v1/jobs/workers": service.list_workers,
                    "/v1/jobs/wake-on-lan": service.read_wake_on_lan,
                    "/v1/incidents/logs": service.read_log_analysis,
                    "/v1/jobs/workers/pairings": service.list_worker_pairings,
                    "/v1/pairings/companions": service.list_companion_pairings,
                    "/v1/companions": service.list_companion_devices,
                    "/v1/incidents": service.list_incidents,
                    "/v1/incidents/resolved": partial(
                        service.list_incidents, "resolved"
                    ),
                    "/v1/incidents/all": partial(service.list_incidents, "all"),
                    "/v1/investigations": service.list_investigations,
                }
                operation = routes.get(path)

                if operation is None and path.startswith("/v1/plugins/"):
                    identifier = path.removeprefix("/v1/plugins/")

                    if identifier and "/" not in identifier:
                        plugin_identifier = identifier

                        def operation() -> object:
                            return service.read_plugin(plugin_identifier)

                if operation is None and path.startswith("/v1/jobs/"):
                    job_id = path.removeprefix("/v1/jobs/")
                    if job_id and "/" not in job_id:
                        operation = partial(service.read_job, job_id)

                if operation is None and path.startswith("/v1/incidents/"):
                    incident_id = path.removeprefix("/v1/incidents/")
                    if incident_id and "/" not in incident_id:
                        operation = partial(service.read_incident, incident_id)

                if operation is None:
                    self._write_error(
                        HTTPStatus.NOT_FOUND,
                        "Administration endpoint not found",
                    )
                    return

                self._execute(operation)

            def do_PUT(self) -> None:  # noqa: N802
                """Handle configuration changes."""
                if worker_only:
                    self._write_error(HTTPStatus.NOT_FOUND, "Worker endpoint not found")
                    return
                if not self._authorized(expected_token, "administration"):
                    return

                path = self.path.split("?", 1)[0]
                routes: dict[str, Callable[[dict[str, Any]], object]] = {
                    "/v1/infrastructure": service.write_infrastructure,
                    "/v1/dhcp": service.write_dhcp,
                    "/v1/system/network": service.write_network,
                    "/v1/jobs/wake-on-lan": service.write_wake_on_lan,
                    "/v1/incidents/logs": service.write_log_analysis,
                }
                operation = routes.get(path)

                if operation is None and path.startswith("/v1/plugins/"):
                    identifier = path.removeprefix("/v1/plugins/")

                    if identifier and "/" not in identifier:
                        plugin_identifier = identifier

                        def operation(payload: object) -> object:
                            return service.write_plugin(
                                plugin_identifier,
                                payload,
                            )

                if operation is None:
                    self._write_error(
                        HTTPStatus.NOT_FOUND,
                        "Administration endpoint not found",
                    )
                    return

                payload = self._read_json()

                if payload is None:
                    return

                self._execute(
                    lambda: operation(payload),
                )

            def do_POST(self) -> None:  # noqa: N802
                """Handle immediate administration actions."""
                path = self.path.split("?", 1)[0]
                if companion_only:
                    pairing_prefix = "/v1/pairings/companions/"
                    if path == "/v1/pairings/companions":
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.create_companion_pairing(payload)
                            )
                        return
                    if path.startswith(pairing_prefix) and path.endswith("/poll"):
                        pairing_id = path[len(pairing_prefix) : -len("/poll")]
                        if pairing_id and "/" not in pairing_id:
                            payload = self._read_json()
                            if payload is not None:
                                self._execute(
                                    lambda: service.poll_companion_pairing(
                                        pairing_id, payload
                                    )
                                )
                        else:
                            self._write_error(
                                HTTPStatus.NOT_FOUND,
                                "Companion endpoint not found",
                            )
                        return
                    identity = self._companion_identity()
                    if identity is None:
                        return
                    if path == "/v1/companions/notifications":
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.register_companion_notifications(
                                    identity, payload
                                )
                            )
                        return
                    response_prefix = "/v1/incidents/requests/"
                    diagnosis_prefix = "/v1/incidents/"
                    if path.startswith(diagnosis_prefix) and path.endswith("/diagnose"):
                        incident_id = path[len(diagnosis_prefix) : -len("/diagnose")]
                        if incident_id and "/" not in incident_id:
                            payload = self._read_json()
                            if payload is not None:
                                if payload:
                                    self._write_error(
                                        HTTPStatus.BAD_REQUEST,
                                        "No parameters are accepted",
                                    )
                                else:
                                    self._execute(
                                        lambda: service.request_companion_diagnosis(
                                            incident_id, identity
                                        )
                                    )
                            return
                    response_suffix = "/response"
                    if path.startswith(response_prefix) and path.endswith(
                        response_suffix
                    ):
                        request_id = path[len(response_prefix) : -len(response_suffix)]
                        if request_id and "/" not in request_id:
                            payload = self._read_json()
                            if payload is not None:
                                self._execute(
                                    lambda: service.respond_companion_request(
                                        request_id, identity, payload
                                    )
                                )
                            return
                    self._write_error(
                        HTTPStatus.NOT_FOUND, "Companion endpoint not found"
                    )
                    return
                artifact_suffix = "/artifact"
                if path.startswith("/v1/jobs/") and path.endswith(artifact_suffix):
                    job_id = path[len("/v1/jobs/") : -len(artifact_suffix)]
                    if job_id and "/" not in job_id:
                        self._upload_backup_artifact(job_id)
                    else:
                        self._write_error(
                            HTTPStatus.NOT_FOUND, "Worker endpoint not found"
                        )
                    return
                if path == "/v1/jobs/workers/pairings":
                    payload = self._read_json()
                    if payload is not None:
                        self._execute(lambda: service.create_worker_pairing(payload))
                    return

                pairing_prefix = "/v1/jobs/workers/pairings/"
                pairing_poll_suffix = "/poll"
                if path.startswith(pairing_prefix) and path.endswith(
                    pairing_poll_suffix
                ):
                    pairing_id = path[len(pairing_prefix) : -len(pairing_poll_suffix)]
                    if pairing_id and "/" not in pairing_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                partial(
                                    service.poll_worker_pairing,
                                    pairing_id,
                                    payload,
                                )
                            )
                        return

                if path == "/v1/jobs/workers/register":
                    payload = self._read_json()
                    previous_worker_id = (
                        self.headers.get("X-Ohana-Previous-Worker-Id", "").strip()
                        or None
                    )
                    if payload is not None and self._authorized_worker(
                        payload,
                        previous_worker_id=previous_worker_id,
                    ):
                        self._execute(
                            lambda: service.register_worker(
                                payload,
                                previous_worker_id=previous_worker_id,
                            )
                        )
                    return
                if path == "/v1/jobs/claim":
                    payload = self._read_json()
                    if payload is not None and self._authorized_worker(payload):
                        self._execute(lambda: service.claim_job(payload))
                    return

                if path == "/v1/jobs/next":
                    payload = self._read_json()
                    if payload is not None and self._authorized_worker(payload):
                        self._execute(lambda: service.next_worker_job(payload))
                    return

                jobs_prefix = "/v1/jobs/"
                for action, operation in (
                    ("heartbeat", service.heartbeat_job),
                    ("complete", service.complete_job),
                ):
                    action_suffix = f"/{action}"
                    if path.startswith(jobs_prefix) and path.endswith(action_suffix):
                        job_id = path[len(jobs_prefix) : -len(action_suffix)]
                        if job_id and "/" not in job_id:
                            payload = self._read_json()
                            if payload is not None and self._authorized_worker(payload):
                                self._execute(partial(operation, job_id, payload))
                            return

                if worker_only:
                    self._write_error(HTTPStatus.NOT_FOUND, "Worker endpoint not found")
                    return

                if not self._authorized(expected_token, "administration"):
                    return

                companion_pairing_prefix = "/v1/pairings/companions/"
                for action, operation in (
                    ("approve", service.approve_companion_pairing),
                    ("reject", service.reject_companion_pairing),
                ):
                    suffix = f"/{action}"
                    if path.startswith(companion_pairing_prefix) and path.endswith(
                        suffix
                    ):
                        pairing_id = path[len(companion_pairing_prefix) : -len(suffix)]
                        if pairing_id and "/" not in pairing_id:
                            self._execute(partial(operation, pairing_id))
                            return
                companion_prefix = "/v1/companions/"
                revoke_suffix = "/revoke"
                if path.startswith(companion_prefix) and path.endswith(revoke_suffix):
                    device_id = path[len(companion_prefix) : -len(revoke_suffix)]
                    if device_id and "/" not in device_id:
                        self._execute(
                            partial(service.revoke_companion_device, device_id)
                        )
                        return

                worker_wake_prefix = "/v1/jobs/workers/"
                worker_wake_suffix = "/wake"
                if path.startswith(worker_wake_prefix) and path.endswith(
                    worker_wake_suffix
                ):
                    worker_id = path[len(worker_wake_prefix) : -len(worker_wake_suffix)]
                    if worker_id and "/" not in worker_id:
                        self._execute(partial(service.wake_worker, worker_id))
                    else:
                        self._write_error(
                            HTTPStatus.NOT_FOUND, "Worker endpoint not found"
                        )
                    return

                if path == "/v1/jobs":
                    payload = self._read_json()
                    if payload is not None:
                        self._execute(lambda: service.create_job(payload))
                    return

                if path == "/v1/investigations":
                    payload = self._read_json()
                    if payload is not None:
                        self._execute(lambda: service.execute_investigation(payload))
                    return

                if path == "/v1/incidents/logs/check":
                    self._execute(service.request_log_health_check)
                    return

                incident_prefix = "/v1/incidents/"
                record_suffix = "/records"
                diagnose_suffix = "/diagnose"
                logs_investigate_suffix = "/logs/investigate"
                repair_authorize_suffix = "/repairs/authorize"
                repairs_suffix = "/repairs"
                experience_suffix = "/experience"
                if path.startswith(incident_prefix) and path.endswith(
                    logs_investigate_suffix
                ):
                    incident_id = path[
                        len(incident_prefix) : -len(logs_investigate_suffix)
                    ]
                    if incident_id and "/" not in incident_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.request_log_investigation(
                                    incident_id, payload
                                )
                            )
                    return
                if path.startswith(incident_prefix) and path.endswith(
                    repair_authorize_suffix
                ):
                    incident_id = path[
                        len(incident_prefix) : -len(repair_authorize_suffix)
                    ]
                    if incident_id and "/" not in incident_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.authorize_incident_repair(
                                    incident_id, payload
                                )
                            )
                    return
                if path.startswith(incident_prefix) and path.endswith(repairs_suffix):
                    incident_id = path[len(incident_prefix) : -len(repairs_suffix)]
                    if incident_id and "/" not in incident_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.propose_incident_repair(
                                    incident_id, payload
                                )
                            )
                    return
                if path.startswith(incident_prefix) and path.endswith(
                    experience_suffix
                ):
                    incident_id = path[len(incident_prefix) : -len(experience_suffix)]
                    if incident_id and "/" not in incident_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.confirm_incident_experience(
                                    incident_id, payload
                                )
                            )
                    return
                if path.startswith(incident_prefix) and path.endswith(diagnose_suffix):
                    incident_id = path[len(incident_prefix) : -len(diagnose_suffix)]
                    if incident_id and "/" not in incident_id:
                        self._execute(partial(service.diagnose_incident, incident_id))
                    return
                if path.startswith(incident_prefix) and path.endswith(record_suffix):
                    incident_id = path[len(incident_prefix) : -len(record_suffix)]
                    if incident_id and "/" not in incident_id:
                        payload = self._read_json()
                        if payload is not None:
                            self._execute(
                                lambda: service.append_incident_record(
                                    incident_id, payload
                                )
                            )
                        return

                for action, operation in (
                    ("approve", service.approve_worker_pairing),
                    ("reject", service.reject_worker_pairing),
                ):
                    suffix = f"/{action}"
                    if path.startswith(pairing_prefix) and path.endswith(suffix):
                        pairing_id = path[len(pairing_prefix) : -len(suffix)]
                        if pairing_id and "/" not in pairing_id:
                            self._execute(partial(operation, pairing_id))
                            return

                cancel_suffix = "/cancel"
                if path.startswith(jobs_prefix) and path.endswith(cancel_suffix):
                    job_id = path[len(jobs_prefix) : -len(cancel_suffix)]
                    if job_id and "/" not in job_id:
                        self._execute(partial(service.cancel_job, job_id))
                        return

                prefix = "/v1/plugins/"
                suffix = "/test"

                if path.startswith(prefix) and path.endswith(suffix):
                    identifier = path[len(prefix) : -len(suffix)]

                    if identifier and "/" not in identifier:
                        self._execute(lambda: service.test_plugin(identifier))
                        return

                if path == "/v1/plugins/backup/icloud/connect":
                    payload = self._read_json()
                    if payload is not None:
                        self._execute(lambda: service.connect_backup_icloud(payload))
                    return

                backup_run_prefix = "/v1/plugins/backup/targets/"
                backup_run_suffix = "/run"
                if path.startswith(backup_run_prefix) and path.endswith(
                    backup_run_suffix
                ):
                    target_id = path[len(backup_run_prefix) : -len(backup_run_suffix)]
                    if target_id and "/" not in target_id:
                        self._execute(partial(service.run_backup, target_id))
                        return

                network_prefix = "/v1/system/network/"
                for action, operation in (
                    ("confirm", service.confirm_network),
                    ("rollback", service.rollback_network),
                ):
                    action_suffix = f"/{action}"
                    if path.startswith(network_prefix) and path.endswith(action_suffix):
                        transaction_id = path[len(network_prefix) : -len(action_suffix)]
                        if transaction_id and "/" not in transaction_id:
                            self._execute(partial(operation, transaction_id))
                            return

                self._write_error(
                    HTTPStatus.NOT_FOUND,
                    "Administration endpoint not found",
                )

            def log_message(
                self,
                format: str,
                *args: object,
            ) -> None:
                """Route request logs through Python logging."""
                LOGGER.info(
                    "%s - %s",
                    self.address_string(),
                    format % args,
                )

            def _authorized(self, token: str | None, role: str) -> bool:
                authorization = self.headers.get("Authorization", "")
                prefix = "Bearer "

                if (
                    token is None
                    or not authorization.startswith(prefix)
                    or not hmac.compare_digest(
                        authorization.removeprefix(prefix),
                        token,
                    )
                ):
                    self._write_error(
                        HTTPStatus.UNAUTHORIZED,
                        f"A valid {role} token is required",
                    )
                    return False

                return True

            def _authorized_worker(
                self,
                payload: dict[str, Any],
                *,
                previous_worker_id: str | None = None,
            ) -> bool:
                authorization = self.headers.get("Authorization", "")
                prefix = "Bearer "
                worker_id = payload.get("worker_id")
                supplied_token = authorization.removeprefix(prefix)
                shared_matches = (
                    expected_worker_token is not None
                    and authorization.startswith(prefix)
                    and hmac.compare_digest(supplied_token, expected_worker_token)
                )
                paired_matches = (
                    isinstance(worker_id, str)
                    and authorization.startswith(prefix)
                    and service.job_repository is not None
                    and service.job_repository.authorize_worker(
                        worker_id,
                        supplied_token,
                        previous_worker_id=previous_worker_id,
                    )
                )
                authorized = (
                    paired_matches
                    if previous_worker_id is not None
                    else shared_matches or paired_matches
                )
                if not authorized:
                    self._write_error(
                        HTTPStatus.UNAUTHORIZED,
                        "A valid worker token is required",
                    )
                    return False
                return True

            def _companion_identity(self) -> str | None:
                """Authorize only one paired companion on the limited listener."""
                device_id = self.headers.get("X-Ohana-Companion-Id", "").strip()
                authorization = self.headers.get("Authorization", "")
                prefix = "Bearer "
                supplied_token = authorization.removeprefix(prefix)
                authorized = (
                    bool(device_id)
                    and authorization.startswith(prefix)
                    and service.companion_repository is not None
                    and service.companion_repository.authorize(
                        device_id, supplied_token
                    )
                )
                if not authorized:
                    self._write_error(
                        HTTPStatus.UNAUTHORIZED,
                        "A valid companion session is required",
                    )
                    return None
                return device_id

            def _worker_transfer_identity(self) -> tuple[str, int] | None:
                worker_id = self.headers.get("X-Ohana-Worker-Id", "").strip()
                try:
                    attempt = int(self.headers.get("X-Ohana-Attempt", "0"))
                except ValueError:
                    attempt = 0
                payload = {"worker_id": worker_id}
                if not worker_id:
                    self._write_error(HTTPStatus.BAD_REQUEST, "Worker ID is required")
                    return None
                if attempt < 1:
                    self._write_error(HTTPStatus.BAD_REQUEST, "Invalid job attempt")
                    return None
                if not self._authorized_worker(payload):
                    return None
                return worker_id, attempt

            def _download_backup_source(self, job_id: str) -> None:
                identity = self._worker_transfer_identity()
                if identity is None:
                    return
                worker_id, attempt = identity
                response_started = False
                try:
                    with service.open_backup_source(
                        job_id, worker_id, attempt
                    ) as stream:
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/x-tar")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.close_connection = True
                        response_started = True
                        stream(self.wfile)
                except LookupError as error:
                    if response_started:
                        LOGGER.exception("Distributed backup source stream failed")
                    else:
                        self._write_error(HTTPStatus.NOT_FOUND, str(error))
                    return
                except DistributedJobConflictError as error:
                    if response_started:
                        LOGGER.exception("Distributed backup source stream failed")
                    else:
                        self._write_error(HTTPStatus.CONFLICT, str(error))
                    return
                except (BrokenPipeError, ConnectionError, OSError):
                    LOGGER.exception("Distributed backup source stream failed")
                except RuntimeError as error:
                    if response_started:
                        LOGGER.exception("Distributed backup source stream failed")
                    else:
                        LOGGER.exception(
                            "Distributed backup source preparation failed for job %s "
                            "(stage=%s)",
                            job_id,
                            getattr(error, "stage", "unknown"),
                        )
                        status = (
                            HTTPStatus.INSUFFICIENT_STORAGE
                            if getattr(error, "stage", None) == "storage"
                            else HTTPStatus.INTERNAL_SERVER_ERROR
                        )
                        self._write_error(
                            status,
                            f"Distributed backup source preparation failed: {error}",
                        )

            def _upload_backup_artifact(self, job_id: str) -> None:
                identity = self._worker_transfer_identity()
                if identity is None:
                    return
                worker_id, attempt = identity
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._write_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
                    return
                sha256 = self.headers.get("X-Ohana-SHA256", "").strip().lower()
                self._execute(
                    lambda: service.receive_backup_artifact(
                        job_id,
                        worker_id,
                        attempt,
                        _BoundedRequestStream(self.rfile, content_length),
                        content_length,
                        sha256,
                    )
                )

            def _read_json(self) -> dict[str, Any] | None:
                raw_length = self.headers.get("Content-Length")

                try:
                    content_length = int(raw_length or "0")
                except ValueError:
                    self._write_error(
                        HTTPStatus.BAD_REQUEST,
                        "Invalid Content-Length header",
                    )
                    return None

                if content_length <= 0 or content_length > MAXIMUM_REQUEST_BYTES:
                    self._write_error(
                        HTTPStatus.BAD_REQUEST,
                        "Administration request body size is invalid",
                    )
                    return None

                try:
                    payload = json.loads(
                        self.rfile.read(content_length).decode("utf-8")
                    )
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._write_error(
                        HTTPStatus.BAD_REQUEST,
                        "Administration request body must be valid JSON",
                    )
                    return None

                if not isinstance(payload, dict):
                    self._write_error(
                        HTTPStatus.BAD_REQUEST,
                        "Administration request body must be a JSON object",
                    )
                    return None

                return payload

            def _execute(
                self,
                operation: Callable[[], object],
            ) -> None:
                try:
                    result = operation()
                except LookupError as error:
                    self._write_error(
                        HTTPStatus.NOT_FOUND,
                        str(error),
                    )
                    return
                except (
                    CompanionConflictError,
                    DistributedJobConflictError,
                    TsunadeExpertiseConflictError,
                ) as error:
                    self._write_error(
                        HTTPStatus.CONFLICT,
                        str(error),
                    )
                    return
                except (
                    DHCPConfigurationError,
                    NetworkAdministrationError,
                    BackupExecutionError,
                    ValidationError,
                    ValueError,
                ) as error:
                    self._write_error(
                        HTTPStatus.UNPROCESSABLE_ENTITY,
                        str(error),
                    )
                    return
                except OSError as error:
                    LOGGER.exception("Administration operation failed")
                    self._write_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        f"Unable to apply administration operation: {error}",
                    )
                    return

                self._write_json(
                    HTTPStatus.OK,
                    result,
                )

            def _write_error(
                self,
                status: HTTPStatus,
                detail: str,
            ) -> None:
                self._write_json(
                    status,
                    {
                        "detail": detail,
                    },
                )

            def _write_json(
                self,
                status: HTTPStatus,
                payload: object,
            ) -> None:
                if hasattr(payload, "model_dump"):
                    payload = payload.model_dump(  # type: ignore[union-attr]
                        mode="json"
                    )

                content = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.send_response(status)
                self.send_header(
                    "Content-Type",
                    "application/json; charset=utf-8",
                )
                self.send_header(
                    "Content-Length",
                    str(len(content)),
                )
                self.end_headers()
                self.wfile.write(content)

        return AdministrationRequestHandler


class AdministrationServerGroup:
    """Start and stop the local administration and worker HTTPS listeners together."""

    def __init__(self, *servers: AdministrationHTTPServer) -> None:
        if not servers:
            raise ValueError("At least one administration server is required")
        self.servers = servers

    def start(self) -> None:
        started: list[AdministrationHTTPServer] = []
        try:
            for server in self.servers:
                server.start()
                started.append(server)
        except Exception:
            for server in reversed(started):
                server.stop()
            raise

    def stop(self) -> None:
        for server in reversed(self.servers):
            server.stop()


def certificate_sha256(path: Path) -> tuple[str, str]:
    """Read one public PEM certificate and return its normalized SHA-256."""
    pem = path.read_text(encoding="ascii")
    der = ssl.PEM_cert_to_DER_cert(pem)
    return pem, hashlib.sha256(der).hexdigest()
