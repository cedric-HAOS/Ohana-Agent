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
        on_infrastructure_changed: (
            Callable[[InfrastructureConfig], None] | None
        ) = None,
        agent_version: str | None = None,
    ) -> None:
        self.infrastructure_repository = infrastructure_repository
        self.dhcp_repository = dhcp_repository
        self.plugin_repository = plugin_repository
        self.network_repository = network_repository
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


class AdministrationHTTPServer:
    """Run the administration API in a dedicated loopback thread."""

    def __init__(
        self,
        *,
        service: AdministrationService,
        token: str,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        normalized_token = token.strip()

        if not normalized_token:
            raise ValueError("Administration token cannot be empty.")

        self.service = service
        self.token = normalized_token
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

        class AdministrationRequestHandler(BaseHTTPRequestHandler):
            """Handle one administration request."""

            server_version = "Ohana-Agent-Administration/1"

            def do_GET(self) -> None:  # noqa: N802
                """Handle administration reads."""
                if not self._authorized(expected_token):
                    return

                path = self.path.split("?", 1)[0]
                routes: dict[str, Callable[[], object]] = {
                    "/v1/capabilities": service.capabilities,
                    "/v1/infrastructure": service.read_infrastructure,
                    "/v1/dhcp": service.read_dhcp,
                    "/v1/plugins": service.list_plugins,
                    "/v1/system/network": service.read_network,
                }
                operation = routes.get(path)

                if operation is None and path.startswith("/v1/plugins/"):
                    identifier = path.removeprefix("/v1/plugins/")

                    if identifier and "/" not in identifier:
                        plugin_identifier = identifier

                        def operation() -> object:
                            return service.read_plugin(plugin_identifier)

                if operation is None:
                    self._write_error(
                        HTTPStatus.NOT_FOUND,
                        "Administration endpoint not found",
                    )
                    return

                self._execute(operation)

            def do_PUT(self) -> None:  # noqa: N802
                """Handle configuration changes."""
                if not self._authorized(expected_token):
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
                if not self._authorized(expected_token):
                    return

                path = self.path.split("?", 1)[0]
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

            def _authorized(self, token: str) -> bool:
                authorization = self.headers.get("Authorization", "")
                prefix = "Bearer "

                if not authorization.startswith(prefix) or not hmac.compare_digest(
                    authorization.removeprefix(prefix),
                    token,
                ):
                    self._write_error(
                        HTTPStatus.UNAUTHORIZED,
                        "A valid administration token is required",
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
