"""Authenticated loopback HTTP API for Agent administration."""

from __future__ import annotations

import hmac
import json
import logging
from collections.abc import Callable
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from threading import Thread
from typing import Any

from pydantic import ValidationError

from administration.dhcp import (
    DHCPConfigurationError,
    DnsmasqDHCPRepository,
)
from administration.infrastructure import (
    InfrastructureConfigurationRepository,
)
from administration.jobs import (
    DistributedJobConflictError,
    DistributedJobRepository,
)
from administration.models import (
    AdministrationCapabilities,
    DHCPConfiguration,
)
from administration.network import (
    NetworkAdministrationError,
    NetworkManagerRepository,
)
from administration.plugins import PluginAdministrationRepository
from configuration.infrastructure import InfrastructureConfig

LOGGER = logging.getLogger(__name__)
MAXIMUM_REQUEST_BYTES = 1024 * 1024


class AdministrationService:
    """Execute versioned administration operations owned by Agent."""

    def __init__(
        self,
        *,
        infrastructure_repository: InfrastructureConfigurationRepository,
        dhcp_repository: DnsmasqDHCPRepository | None = None,
        plugin_repository: PluginAdministrationRepository | None = None,
        network_repository: NetworkManagerRepository | None = None,
        job_repository: DistributedJobRepository | None = None,
        on_infrastructure_changed: (
            Callable[[InfrastructureConfig], None] | None
        ) = None,
        agent_version: str | None = None,
    ) -> None:
        self.infrastructure_repository = infrastructure_repository
        self.dhcp_repository = dhcp_repository
        self.plugin_repository = plugin_repository
        self.network_repository = network_repository
        self.job_repository = job_repository
        self.on_infrastructure_changed = on_infrastructure_changed
        self.agent_version = agent_version or self._installed_agent_version()

    def capabilities(self) -> AdministrationCapabilities:
        """Declare the operations actually supported by this Agent."""
        operations = [
            "infrastructure.read",
            "infrastructure.write",
        ]

        if self.dhcp_repository is not None:
            operations.extend(
                [
                    "dhcp.read",
                    "dhcp.write",
                    "dhcp.leases.read",
                ]
            )

        if self.network_repository is not None:
            operations.extend(
                [
                    "system.network.read",
                    "system.network.write",
                    "system.network.confirm",
                    "system.network.rollback",
                ]
            )

        if self.plugin_repository is not None:
            operations.extend(
                [
                    "plugins.read",
                    "plugins.write",
                    "plugins.test",
                    "plugins.backup.icloud.connect",
                    "plugins.backup.run",
                ]
            )

        if self.job_repository is not None:
            operations.extend(
                [
                    "jobs.create",
                    "jobs.read",
                    "jobs.cancel",
                    "jobs.workers.read",
                    "jobs.workers.pairings.read",
                    "jobs.workers.pairings.approve",
                    "jobs.workers.pairings.reject",
                    "jobs.worker.pair",
                    "jobs.worker.register",
                    "jobs.worker.claim",
                    "jobs.worker.heartbeat",
                    "jobs.worker.complete",
                ]
            )

        return AdministrationCapabilities(
            agent_version=self.agent_version,
            operations=operations,
        )

    @staticmethod
    def _installed_agent_version() -> str:
        """Return the installed Ohana-Agent package version."""
        try:
            return package_version("ohana-agent")
        except PackageNotFoundError:
            return "unknown"

    def read_infrastructure(self) -> InfrastructureConfig:
        """Read the Agent-owned infrastructure definition."""
        return self.infrastructure_repository.read()

    def write_infrastructure(
        self,
        payload: dict[str, Any],
    ) -> InfrastructureConfig:
        """Validate, persist and publish an infrastructure definition."""
        configuration = InfrastructureConfig.model_validate(payload)
        saved_configuration = self.infrastructure_repository.write(configuration)

        if self.on_infrastructure_changed is not None:
            self.on_infrastructure_changed(saved_configuration)

        return saved_configuration

    def read_dhcp(self) -> object:
        """Return the DHCP configuration and active leases."""
        if self.dhcp_repository is None:
            raise LookupError("DHCP administration is unavailable")

        return self.dhcp_repository.read()

    def write_dhcp(
        self,
        payload: dict[str, Any],
    ) -> object:
        """Validate and persist the DHCP configuration."""
        if self.dhcp_repository is None:
            raise LookupError("DHCP administration is unavailable")

        configuration = DHCPConfiguration.model_validate(payload)
        return self.dhcp_repository.write(configuration)

    def read_network(self) -> object:
        """Return the active NetworkManager configuration of the Agent host."""
        if self.network_repository is None:
            raise LookupError("Agent network administration is unavailable")
        return self.network_repository.read()

    def write_network(self, payload: dict[str, Any]) -> object:
        """Apply a candidate host network configuration with rollback protection."""
        if self.network_repository is None:
            raise LookupError("Agent network administration is unavailable")
        return self.network_repository.apply(payload)

    def confirm_network(self, transaction_id: str) -> object:
        """Confirm a pending host network configuration."""
        if self.network_repository is None:
            raise LookupError("Agent network administration is unavailable")
        return self.network_repository.confirm(transaction_id)

    def rollback_network(self, transaction_id: str) -> object:
        """Restore the previous host network configuration immediately."""
        if self.network_repository is None:
            raise LookupError("Agent network administration is unavailable")
        return self.network_repository.rollback(transaction_id)

    def list_plugins(self) -> object:
        """Return all registered and administrable plugins."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")

        return self.plugin_repository.list()

    def read_plugin(self, identifier: str) -> object:
        """Return one plugin configuration and runtime state."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")

        return self.plugin_repository.read(identifier)

    def write_plugin(
        self,
        identifier: str,
        payload: dict[str, Any],
    ) -> object:
        """Persist and immediately apply one plugin configuration."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")

        return self.plugin_repository.write(identifier, payload)

    def test_plugin(self, identifier: str) -> object:
        """Execute one immediate plugin capability check."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")

        return self.plugin_repository.test(identifier)

    def connect_backup_icloud(self, payload: dict[str, Any]) -> object:
        """Start or complete the iCloud authentication flow."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")
        return self.plugin_repository.connect_backup_icloud(payload)

    def run_backup(self, target_id: str) -> object:
        """Start one configured HAOS backup in the background."""
        if self.plugin_repository is None:
            raise LookupError("Plugin administration is unavailable")
        return self.plugin_repository.run_backup(target_id)

    def create_job(self, payload: dict[str, Any]) -> object:
        """Validate and queue one explicitly typed distributed job."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.create(payload)

    def read_job(self, job_id: str) -> object:
        """Read the current durable state of one job."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.get(job_id)

    def cancel_job(self, job_id: str) -> object:
        """Cancel one job through the Tsunade control plane."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.cancel(job_id)

    def claim_job(self, payload: dict[str, Any]) -> object:
        """Lease the oldest compatible job to Katsuyu."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.claim(payload)

    def register_worker(self, payload: dict[str, Any]) -> object:
        """Register Katsuyu and its finite capabilities."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.register_worker(payload)

    def list_workers(self) -> object:
        """List the worker registrations visible to Tsunade."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.list_workers()

    def create_worker_pairing(self, payload: dict[str, Any]) -> object:
        """Open a bounded Katsuyu pairing request for later approval."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.create_pairing(payload)

    def list_worker_pairings(self) -> object:
        """List pairing requests visible to the administration plane."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.list_pairings()

    def approve_worker_pairing(self, pairing_id: str) -> object:
        """Approve one verification code checked by the administrator."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.approve_pairing(pairing_id)

    def reject_worker_pairing(self, pairing_id: str) -> object:
        """Reject one untrusted or obsolete pairing request."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.reject_pairing(pairing_id)

    def poll_worker_pairing(self, pairing_id: str, payload: dict[str, Any]) -> object:
        """Let the originating installer retrieve its credential once."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.poll_pairing(pairing_id, payload)

    def heartbeat_job(self, job_id: str, payload: dict[str, Any]) -> object:
        """Renew a job lease for its current Katsuyu attempt."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.heartbeat(job_id, payload)

    def complete_job(self, job_id: str, payload: dict[str, Any]) -> object:
        """Record a verified result from the current Katsuyu attempt."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return self.job_repository.complete(job_id, payload)


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
        self._server = ThreadingHTTPServer(
            (self.host, self.port),
            handler_class,
        )
        self._thread = Thread(
            target=self._server.serve_forever,
            name="ohana-agent-administration",
            daemon=True,
        )
        self._thread.start()
        LOGGER.info(
            "Administration API listening on http://%s:%s",
            *self.address,
        )

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

        class AdministrationRequestHandler(BaseHTTPRequestHandler):
            """Handle one administration request."""

            server_version = "Ohana-Agent-Administration/1"

            def do_GET(self) -> None:  # noqa: N802
                """Handle administration reads."""
                if not self._authorized(expected_token, "administration"):
                    return

                path = self.path.split("?", 1)[0]
                routes: dict[str, Callable[[], object]] = {
                    "/v1/capabilities": service.capabilities,
                    "/v1/infrastructure": service.read_infrastructure,
                    "/v1/dhcp": service.read_dhcp,
                    "/v1/plugins": service.list_plugins,
                    "/v1/system/network": service.read_network,
                    "/v1/jobs/workers": service.list_workers,
                    "/v1/jobs/workers/pairings": service.list_worker_pairings,
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

                if operation is None:
                    self._write_error(
                        HTTPStatus.NOT_FOUND,
                        "Administration endpoint not found",
                    )
                    return

                self._execute(operation)

            def do_PUT(self) -> None:  # noqa: N802
                """Handle configuration changes."""
                if not self._authorized(expected_token, "administration"):
                    return

                path = self.path.split("?", 1)[0]
                routes: dict[str, Callable[[dict[str, Any]], object]] = {
                    "/v1/infrastructure": service.write_infrastructure,
                    "/v1/dhcp": service.write_dhcp,
                    "/v1/system/network": service.write_network,
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
                    if payload is not None and self._authorized_worker(payload):
                        self._execute(lambda: service.register_worker(payload))
                    return
                if path == "/v1/jobs/claim":
                    payload = self._read_json()
                    if payload is not None and self._authorized_worker(payload):
                        self._execute(lambda: service.claim_job(payload))
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

                if not self._authorized(expected_token, "administration"):
                    return

                if path == "/v1/jobs":
                    payload = self._read_json()
                    if payload is not None:
                        self._execute(lambda: service.create_job(payload))
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

            def _authorized_worker(self, payload: dict[str, Any]) -> bool:
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
                        worker_id, supplied_token
                    )
                )
                if not shared_matches and not paired_matches:
                    self._write_error(
                        HTTPStatus.UNAUTHORIZED,
                        "A valid worker token is required",
                    )
                    return False
                return True

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
                except DistributedJobConflictError as error:
                    self._write_error(
                        HTTPStatus.CONFLICT,
                        str(error),
                    )
                    return
                except (
                    DHCPConfigurationError,
                    NetworkAdministrationError,
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
