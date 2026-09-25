"""Authenticated HTTP API for Agent administration, served by aiohttp."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import ssl
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import Any

from aiohttp import web
from pydantic import ValidationError

from ohana_agent.api.service import AdministrationService
from ohana_agent.companions.repository import (
    CompanionConflictError,
)
from ohana_agent.core.http_listener import (
    BlockingRequestReader,
    BlockingResponseWriter,
    ThreadedHTTPListener,
    call_on_loop,
    json_response,
)
from ohana_agent.host.dhcp import DHCPConfigurationError
from ohana_agent.host.network import (
    NetworkAdministrationError,
)
from ohana_agent.jobs.repository import (
    DistributedJobConflictError,
)
from ohana_agent.plugins.backup.coordinator import BackupExecutionError
from ohana_agent.tsunade.expertise_catalog import (
    TsunadeExpertiseConflictError,
)

LOGGER = logging.getLogger(__name__)
MAXIMUM_REQUEST_BYTES = 1024 * 1024
BEARER_PREFIX = "Bearer "

ADMINISTRATION_NOT_FOUND = "Administration endpoint not found"
WORKER_NOT_FOUND = "Worker endpoint not found"
COMPANION_NOT_FOUND = "Companion endpoint not found"

# First match wins, so subclasses must precede their base classes.
_OPERATION_ERROR_STATUSES: tuple[
    tuple[tuple[type[Exception], ...], HTTPStatus], ...
] = (
    ((LookupError,), HTTPStatus.NOT_FOUND),
    (
        (
            CompanionConflictError,
            DistributedJobConflictError,
            TsunadeExpertiseConflictError,
        ),
        HTTPStatus.CONFLICT,
    ),
    (
        (
            DHCPConfigurationError,
            NetworkAdministrationError,
            BackupExecutionError,
            ValidationError,
            ValueError,
        ),
        HTTPStatus.UNPROCESSABLE_ENTITY,
    ),
)


class _Rejected(Exception):
    """Stop handling one request with a JSON error response."""

    def __init__(self, status: HTTPStatus, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _error_response(status: HTTPStatus, detail: str) -> web.Response:
    return json_response(status, {"detail": detail})


Handler = Callable[["_Call", Mapping[str, str]], Awaitable[web.StreamResponse]]


@dataclass(frozen=True, slots=True)
class _Route:
    pattern: re.Pattern[str]
    handler: Handler


@dataclass(frozen=True, slots=True)
class _Guard:
    """Authorize every route listed after it in the same table."""

    check: Callable[[_Call], Awaitable[None]]


_RouteTable = tuple[_Route | _Guard, ...]


def _route(template: str, handler: Handler) -> _Route:
    """Compile ``/v1/jobs/{job_id}`` into a single-segment path matcher."""
    expression = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template)
    return _Route(re.compile(f"^{expression}$"), handler)


def _call(operation: Callable[..., object]) -> Handler:
    """Run ``operation(*path parameters)``."""

    async def handler(call: _Call, parameters: Mapping[str, str]) -> web.Response:
        return await call.execute(partial(operation, *parameters.values()))

    return handler


def _call_with_body(operation: Callable[..., object]) -> Handler:
    """Run ``operation(*path parameters, json body)``."""

    async def handler(call: _Call, parameters: Mapping[str, str]) -> web.Response:
        payload = await call.json()
        return await call.execute(partial(operation, *parameters.values(), payload))

    return handler


def _worker_call_with_body(operation: Callable[..., object]) -> Handler:
    """Run ``operation(*path parameters, json body)`` for an authorized worker."""

    async def handler(call: _Call, parameters: Mapping[str, str]) -> web.Response:
        payload = await call.json()
        await call.authorize_worker(payload)
        return await call.execute(partial(operation, *parameters.values(), payload))

    return handler


def _companion_call_with_body(operation: Callable[..., object]) -> Handler:
    """Run ``operation(*path parameters, companion id, json body)``."""

    async def handler(call: _Call, parameters: Mapping[str, str]) -> web.Response:
        payload = await call.json()
        return await call.execute(
            partial(operation, *parameters.values(), call.companion_id, payload)
        )

    return handler


class _Call:
    """Request helpers shared by every administration route."""

    def __init__(self, server: AdministrationHTTPServer, request: web.Request) -> None:
        self.server = server
        self.service = server.service
        self.request = request
        self.companion_id: str | None = None

    def header(self, name: str) -> str:
        return self.request.headers.get(name, "")

    def bearer_token(self) -> str | None:
        authorization = self.header("Authorization")

        if not authorization.startswith(BEARER_PREFIX):
            return None

        return authorization.removeprefix(BEARER_PREFIX)

    async def json(self) -> dict[str, Any]:
        content_length = self.request.content_length or 0

        if content_length <= 0 or content_length > MAXIMUM_REQUEST_BYTES:
            raise _Rejected(
                HTTPStatus.BAD_REQUEST,
                "Administration request body size is invalid",
            )

        try:
            payload = json.loads((await self.request.read()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _Rejected(
                HTTPStatus.BAD_REQUEST,
                "Administration request body must be valid JSON",
            ) from error

        if not isinstance(payload, dict):
            raise _Rejected(
                HTTPStatus.BAD_REQUEST,
                "Administration request body must be a JSON object",
            )

        return payload

    async def execute(self, operation: Callable[[], object]) -> web.Response:
        """Run one blocking service operation and map domain errors to HTTP."""
        try:
            result = await self.server.run_blocking(operation)
        except OSError as error:
            LOGGER.exception("Administration operation failed")
            return _error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"Unable to apply administration operation: {error}",
            )
        except Exception as error:
            for error_types, status in _OPERATION_ERROR_STATUSES:
                if isinstance(error, error_types):
                    return _error_response(status, str(error))
            raise

        return json_response(HTTPStatus.OK, result)

    async def authorize_administration(self) -> None:
        token = self.bearer_token()

        if token is None or not hmac.compare_digest(token, self.server.token):
            raise _Rejected(
                HTTPStatus.UNAUTHORIZED,
                "A valid administration token is required",
            )

    async def authorize_worker(
        self,
        payload: Mapping[str, Any],
        *,
        previous_worker_id: str | None = None,
    ) -> None:
        token = self.bearer_token()
        worker_id = payload.get("worker_id")
        expected_worker_token = self.server.worker_token
        shared_matches = (
            expected_worker_token is not None
            and token is not None
            and hmac.compare_digest(token, expected_worker_token)
        )
        repository = self.service.job_repository
        paired_matches = (
            isinstance(worker_id, str)
            and token is not None
            and repository is not None
            and await self.server.run_blocking(
                partial(
                    repository.authorize_worker,
                    worker_id,
                    token,
                    previous_worker_id=previous_worker_id,
                )
            )
        )
        authorized = (
            paired_matches
            if previous_worker_id is not None
            else shared_matches or paired_matches
        )

        if not authorized:
            raise _Rejected(
                HTTPStatus.UNAUTHORIZED,
                "A valid worker token is required",
            )

    async def authorize_companion(self) -> None:
        """Authorize only one paired companion on the limited listener."""
        device_id = self.header("X-Ohana-Companion-Id").strip()
        token = self.bearer_token()
        repository = self.service.companion_repository
        authorized = (
            bool(device_id)
            and token is not None
            and repository is not None
            and await self.server.run_blocking(
                partial(repository.authorize, device_id, token)
            )
        )

        if not authorized:
            raise _Rejected(
                HTTPStatus.UNAUTHORIZED,
                "A valid companion session is required",
            )

        self.companion_id = device_id

    async def worker_transfer_identity(self) -> tuple[str, int]:
        worker_id = self.header("X-Ohana-Worker-Id").strip()

        try:
            attempt = int(self.request.headers.get("X-Ohana-Attempt", "0"))
        except ValueError:
            attempt = 0

        if not worker_id:
            raise _Rejected(HTTPStatus.BAD_REQUEST, "Worker ID is required")

        if attempt < 1:
            raise _Rejected(HTTPStatus.BAD_REQUEST, "Invalid job attempt")

        await self.authorize_worker({"worker_id": worker_id})
        return worker_id, attempt


async def _register_worker(call: _Call, _: Mapping[str, str]) -> web.Response:
    payload = await call.json()
    previous_worker_id = call.header("X-Ohana-Previous-Worker-Id").strip() or None
    await call.authorize_worker(payload, previous_worker_id=previous_worker_id)
    return await call.execute(
        partial(
            call.service.register_worker,
            payload,
            previous_worker_id=previous_worker_id,
        )
    )


async def _read_log_source(call: _Call, parameters: Mapping[str, str]) -> web.Response:
    worker_id, attempt = await call.worker_transfer_identity()
    return await call.execute(
        partial(
            call.service.read_log_source,
            parameters["job_id"],
            worker_id,
            attempt,
            parameters["source_id"],
        )
    )


async def _upload_backup_artifact(
    call: _Call,
    parameters: Mapping[str, str],
) -> web.Response:
    worker_id, attempt = await call.worker_transfer_identity()
    content_length = call.request.content_length or 0
    sha256 = call.header("X-Ohana-SHA256").strip().lower()
    stream = BlockingRequestReader(
        call.request,
        asyncio.get_running_loop(),
        content_length,
    )
    return await call.execute(
        partial(
            call.service.receive_backup_artifact,
            parameters["job_id"],
            worker_id,
            attempt,
            stream,
            content_length,
            sha256,
        )
    )


async def _download_backup_source(
    call: _Call,
    parameters: Mapping[str, str],
) -> web.StreamResponse:
    """Stream the INFRA-01 source tar once the service has prepared it."""
    job_id = parameters["job_id"]
    worker_id, attempt = await call.worker_transfer_identity()
    loop = asyncio.get_running_loop()
    response = web.StreamResponse(
        status=HTTPStatus.OK,
        headers={"Content-Type": "application/x-tar"},
    )
    response.force_close()
    output = BlockingResponseWriter(response, loop)
    started = False

    def transfer() -> None:
        nonlocal started
        with call.service.open_backup_source(job_id, worker_id, attempt) as stream:
            call_on_loop(loop, response.prepare(call.request))
            started = True
            stream(output)
            output.flush()

    try:
        await call.server.run_blocking(transfer)
    except Exception as error:
        if not started:
            return _source_preparation_error(job_id, error)

        # Never terminate the chunked body cleanly: Katsuyu must see a
        # truncated transfer rather than a well-formed partial archive.
        LOGGER.exception("Distributed backup source stream failed")
        if call.request.transport is not None:
            call.request.transport.close()
        return response

    await response.write_eof()
    return response


def _source_preparation_error(job_id: str, error: Exception) -> web.Response:
    if isinstance(error, LookupError):
        return _error_response(HTTPStatus.NOT_FOUND, str(error))

    if isinstance(error, DistributedJobConflictError):
        return _error_response(HTTPStatus.CONFLICT, str(error))

    if not isinstance(error, RuntimeError | OSError):
        raise error

    stage = getattr(error, "stage", "unknown")
    LOGGER.exception(
        "Distributed backup source preparation failed for job %s (stage=%s)",
        job_id,
        stage,
        exc_info=error,
    )
    return _error_response(
        (
            HTTPStatus.INSUFFICIENT_STORAGE
            if stage == "storage"
            else HTTPStatus.INTERNAL_SERVER_ERROR
        ),
        f"Distributed backup source preparation failed: {error}",
    )


async def _companion_trust(call: _Call, _: Mapping[str, str]) -> web.Response:
    service = call.service

    if service.companion_ca_sha256 is None:
        raise _Rejected(HTTPStatus.NOT_FOUND, "Companion trust is unavailable")

    return json_response(
        HTTPStatus.OK,
        {
            "schema_version": 1,
            "tls_ca_sha256": service.companion_ca_sha256,
            "tls_ca_certificate_pem": service.companion_ca_certificate_pem,
        },
    )


async def _companion_diagnosis(
    call: _Call,
    parameters: Mapping[str, str],
) -> web.Response:
    if await call.json():
        raise _Rejected(HTTPStatus.BAD_REQUEST, "No parameters are accepted")

    return await call.execute(
        partial(
            call.service.request_companion_diagnosis,
            parameters["incident_id"],
            call.companion_id,
        )
    )


def _worker_routes(service: AdministrationService) -> _RouteTable:
    """Worker endpoints reachable on both the loopback and worker listeners."""
    return (
        _route("/v1/jobs/{job_id}/artifact", _upload_backup_artifact),
        _route(
            "/v1/jobs/workers/pairings",
            _call_with_body(service.create_worker_pairing),
        ),
        _route(
            "/v1/jobs/workers/pairings/{pairing_id}/poll",
            _call_with_body(service.poll_worker_pairing),
        ),
        _route("/v1/jobs/workers/register", _register_worker),
        _route("/v1/jobs/claim", _worker_call_with_body(service.claim_job)),
        _route("/v1/jobs/next", _worker_call_with_body(service.next_worker_job)),
        _route(
            "/v1/jobs/{job_id}/heartbeat",
            _worker_call_with_body(service.heartbeat_job),
        ),
        _route(
            "/v1/jobs/{job_id}/complete",
            _worker_call_with_body(service.complete_job),
        ),
    )


def _administration_routes(
    service: AdministrationService,
) -> dict[str, _RouteTable]:
    administration = _Guard(_Call.authorize_administration)
    return {
        "GET": (
            administration,
            _route("/v1/capabilities", _call(service.capabilities)),
            _route("/v1/infrastructure", _call(service.read_infrastructure)),
            _route("/v1/dhcp", _call(service.read_dhcp)),
            _route("/v1/plugins", _call(service.list_plugins)),
            _route("/v1/system/network", _call(service.read_network)),
            _route("/v1/jobs/workers", _call(service.list_workers)),
            _route("/v1/jobs/wake-on-lan", _call(service.read_wake_on_lan)),
            _route("/v1/incidents/logs", _call(service.read_log_analysis)),
            _route("/v1/jobs/workers/pairings", _call(service.list_worker_pairings)),
            _route("/v1/pairings/companions", _call(service.list_companion_pairings)),
            _route("/v1/companions", _call(service.list_companion_devices)),
            _route("/v1/incidents", _call(service.list_incidents)),
            _route(
                "/v1/incidents/resolved",
                _call(partial(service.list_incidents, "resolved")),
            ),
            _route("/v1/incidents/all", _call(partial(service.list_incidents, "all"))),
            _route("/v1/investigations", _call(service.list_investigations)),
            _route("/v1/plugins/{identifier}", _call(service.read_plugin)),
            _route("/v1/jobs/{job_id}", _call(service.read_job)),
            _route("/v1/incidents/{incident_id}", _call(service.read_incident)),
        ),
        "PUT": (
            administration,
            _route("/v1/infrastructure", _call_with_body(service.write_infrastructure)),
            _route("/v1/dhcp", _call_with_body(service.write_dhcp)),
            _route("/v1/system/network", _call_with_body(service.write_network)),
            _route(
                "/v1/jobs/wake-on-lan",
                _call_with_body(service.write_wake_on_lan),
            ),
            _route("/v1/incidents/logs", _call_with_body(service.write_log_analysis)),
            _route("/v1/plugins/{identifier}", _call_with_body(service.write_plugin)),
        ),
        "POST": (
            *_worker_routes(service),
            administration,
            _route(
                "/v1/pairings/companions/{pairing_id}/approve",
                _call(service.approve_companion_pairing),
            ),
            _route(
                "/v1/pairings/companions/{pairing_id}/reject",
                _call(service.reject_companion_pairing),
            ),
            _route(
                "/v1/companions/{device_id}/revoke",
                _call(service.revoke_companion_device),
            ),
            _route("/v1/jobs/workers/{worker_id}/wake", _call(service.wake_worker)),
            _route("/v1/jobs", _call_with_body(service.create_job)),
            _route(
                "/v1/investigations",
                _call_with_body(service.execute_investigation),
            ),
            _route(
                "/v1/incidents/logs/check",
                _call(service.request_log_health_check),
            ),
            _route(
                "/v1/incidents/{incident_id}/logs/investigate",
                _call_with_body(service.request_log_investigation),
            ),
            _route(
                "/v1/incidents/{incident_id}/repairs/authorize",
                _call_with_body(service.authorize_incident_repair),
            ),
            _route(
                "/v1/incidents/{incident_id}/repairs",
                _call_with_body(service.propose_incident_repair),
            ),
            _route(
                "/v1/incidents/{incident_id}/experience",
                _call_with_body(service.confirm_incident_experience),
            ),
            _route(
                "/v1/incidents/{incident_id}/diagnose",
                _call(service.diagnose_incident),
            ),
            _route(
                "/v1/incidents/{incident_id}/records",
                _call_with_body(service.append_incident_record),
            ),
            _route(
                "/v1/jobs/workers/pairings/{pairing_id}/approve",
                _call(service.approve_worker_pairing),
            ),
            _route(
                "/v1/jobs/workers/pairings/{pairing_id}/reject",
                _call(service.reject_worker_pairing),
            ),
            _route("/v1/jobs/{job_id}/cancel", _call(service.cancel_job)),
            _route("/v1/plugins/{identifier}/test", _call(service.test_plugin)),
            _route(
                "/v1/plugins/backup/icloud/connect",
                _call_with_body(service.connect_backup_icloud),
            ),
            _route(
                "/v1/plugins/backup/targets/{target_id}/run",
                _call(service.run_backup),
            ),
            _route(
                "/v1/system/network/{transaction_id}/confirm",
                _call(service.confirm_network),
            ),
            _route(
                "/v1/system/network/{transaction_id}/rollback",
                _call(service.rollback_network),
            ),
        ),
    }


def _worker_listener_routes(
    service: AdministrationService,
) -> dict[str, _RouteTable]:
    return {
        "GET": (
            _route("/v1/jobs/{job_id}/input", _download_backup_source),
            _route("/v1/jobs/{job_id}/log-source/{source_id}", _read_log_source),
            _route("/v1/jobs/workers/trust", _call(service.read_worker_trust)),
        ),
        "PUT": (),
        "POST": _worker_routes(service),
    }


def _companion_listener_routes(
    service: AdministrationService,
) -> dict[str, _RouteTable]:
    companion = _Guard(_Call.authorize_companion)
    return {
        "GET": (
            _route("/v1/pairings/companions/trust", _companion_trust),
            companion,
            _route("/v1/incidents/summary", _call(service.read_companion_summary)),
            _route("/v1/incidents/requests", _call(service.read_companion_requests)),
            _route(
                "/v1/incidents/requests/all",
                _call(partial(service.read_companion_requests, "all")),
            ),
            _route("/v1/incidents/activity", _call(service.read_companion_activity)),
        ),
        "PUT": (),
        "POST": (
            _route(
                "/v1/pairings/companions",
                _call_with_body(service.create_companion_pairing),
            ),
            _route(
                "/v1/pairings/companions/{pairing_id}/poll",
                _call_with_body(service.poll_companion_pairing),
            ),
            companion,
            _route(
                "/v1/companions/notifications",
                _companion_call_with_body(service.register_companion_notifications),
            ),
            _route("/v1/incidents/{incident_id}/diagnose", _companion_diagnosis),
            _route(
                "/v1/incidents/requests/{request_id}/response",
                _respond_companion_request,
            ),
        ),
    }


async def _respond_companion_request(
    call: _Call,
    parameters: Mapping[str, str],
) -> web.Response:
    payload = await call.json()
    return await call.execute(
        partial(
            call.service.respond_companion_request,
            parameters["request_id"],
            call.companion_id,
            payload,
        )
    )


class AdministrationHTTPServer(ThreadedHTTPListener):
    """Serve the administration, Katsuyu worker or companion API."""

    server_header = "Ohana-Agent-Administration/1"

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

        super().__init__(host=host, port=port, logger=LOGGER)
        self.service = service
        self.token = normalized_token
        self.worker_token = worker_token.strip() if worker_token else None
        if self.worker_token and hmac.compare_digest(self.worker_token, self.token):
            raise ValueError("Worker and administration tokens must be different.")
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

        if worker_only:
            self.thread_name = "ohana-agent-worker-https"
            self._role = "Katsuyu worker API"
            self._not_found = WORKER_NOT_FOUND
            self._routes = _worker_listener_routes(service)
        elif companion_only:
            self.thread_name = "ohana-agent-companion-https"
            self._role = "Companion API"
            self._not_found = COMPANION_NOT_FOUND
            self._routes = _companion_listener_routes(service)
        else:
            self.thread_name = "ohana-agent-administration"
            self._role = "Administration API"
            self._not_found = ADMINISTRATION_NOT_FOUND
            self._routes = _administration_routes(service)

    def start(self) -> None:
        """Start the HTTP server once."""
        if self.running:
            return

        super().start()
        scheme = "https" if self.tls_certificate_file is not None else "http"
        LOGGER.info("%s listening on %s://%s:%s", self._role, scheme, *self.address)

    def ssl_context(self) -> ssl.SSLContext | None:
        if self.tls_certificate_file is None:
            return None

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(
            certfile=self.tls_certificate_file,
            keyfile=self.tls_private_key_file,
        )
        return context

    def build_application(self) -> web.Application:
        application = web.Application(client_max_size=MAXIMUM_REQUEST_BYTES + 1)
        application.router.add_route("*", "/{path:.*}", self._dispatch)
        return application

    async def _dispatch(self, request: web.Request) -> web.StreamResponse:
        routes = self._routes.get(request.method)

        if routes is None:
            return _error_response(HTTPStatus.NOT_IMPLEMENTED, "Unsupported method")

        call = _Call(self, request)
        path = request.raw_path.split("?", 1)[0]

        try:
            for entry in routes:
                if isinstance(entry, _Guard):
                    await entry.check(call)
                    continue

                match = entry.pattern.match(path)
                if match is not None:
                    return await entry.handler(call, match.groupdict())

            raise _Rejected(HTTPStatus.NOT_FOUND, self._not_found)
        except _Rejected as rejection:
            return _error_response(rejection.status, rejection.detail)
        except Exception:
            LOGGER.exception(
                "Administration request %s %s failed", request.method, path
            )
            return _error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Unexpected administration failure",
            )


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
