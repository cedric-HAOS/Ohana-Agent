"""Dedicated HTTP endpoint receiving frames directly from teleinfo2mqtt."""

from __future__ import annotations

import hmac
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

from plugins.teleinformation.teleinformation_frame_store import (
    TeleinformationFrameStore,
)

LOGGER = logging.getLogger(__name__)
_MAXIMUM_REQUEST_BYTES = 131_072


class TeleinformationIngestionHTTPServer:
    """Small authenticated receiver isolated from the administration API."""

    def __init__(
        self,
        *,
        frame_store: TeleinformationFrameStore,
        token: str,
        host: str = "0.0.0.0",
        port: int = 8770,
    ) -> None:
        self.frame_store = frame_store
        self.host = host
        self.port = port
        self._token = self._normalize_token(token)
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def address(self) -> tuple[str, int] | None:
        if self._server is None:
            return None
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        if self.running:
            return
        self._server = ThreadingHTTPServer(
            (self.host, self.port), self._handler_class()
        )
        self._thread = Thread(
            target=self._server.serve_forever,
            name="ohana-agent-teleinformation-ingestion",
            daemon=True,
        )
        self._thread.start()
        LOGGER.info(
            "Téléinformation ingestion listening on http://%s:%s", *self.address
        )

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def reconfigure(self, *, host: str, port: int, token: str) -> None:
        """Apply listener settings, restarting only when required."""
        normalized_token = self._normalize_token(token)
        restart = self.running and (host != self.host or port != self.port)
        if restart:
            self.stop()
        self.host = host
        self.port = port
        self._token = normalized_token
        if restart:
            self.start()

    @staticmethod
    def _normalize_token(token: str) -> str:
        normalized = token.strip()
        if not normalized:
            raise ValueError("Téléinformation ingestion token cannot be empty.")
        return normalized

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        frame_store = self.frame_store
        server_instance = self

        class TeleinformationRequestHandler(BaseHTTPRequestHandler):
            server_version = "Ohana-Agent-Teleinformation/1"

            def do_POST(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                if path != "/v1/teleinformation/frames":
                    self._write_error(HTTPStatus.NOT_FOUND, "Endpoint not found")
                    return
                if not self._authorized():
                    return
                payload = self._read_json()
                if payload is None:
                    return
                try:
                    schema_version = payload.get("schema_version")
                    if schema_version != 1:
                        raise ValueError("schema_version must be 1.")
                    source = payload.get("source")
                    meter_id = payload.get("meter_id")
                    frame = payload.get("frame")
                    if not isinstance(frame, dict):
                        raise ValueError("frame must be a JSON object.")
                    stored = frame_store.put(
                        source=source,
                        meter_id=meter_id,
                        frame=frame,
                    )
                except ValueError as error:
                    self._write_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(error))
                    return
                self._write_json(
                    HTTPStatus.ACCEPTED,
                    {
                        "accepted": True,
                        "source": stored.source,
                        "meter_id": stored.meter_id,
                        "received_at": stored.received_at.isoformat(),
                    },
                )

            def log_message(self, format: str, *args: object) -> None:
                LOGGER.info("%s - %s", self.address_string(), format % args)

            def _authorized(self) -> bool:
                authorization = self.headers.get("Authorization", "")
                prefix = "Bearer "
                supplied = (
                    authorization.removeprefix(prefix)
                    if authorization.startswith(prefix)
                    else ""
                )
                if not supplied or not hmac.compare_digest(
                    supplied, server_instance._token
                ):
                    self._write_error(
                        HTTPStatus.UNAUTHORIZED,
                        "A valid Téléinformation ingestion token is required",
                    )
                    return False
                return True

            def _read_json(self) -> dict[str, Any] | None:
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._write_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
                    return None
                if content_length <= 0 or content_length > _MAXIMUM_REQUEST_BYTES:
                    self._write_error(
                        HTTPStatus.BAD_REQUEST, "Invalid request body size"
                    )
                    return None
                try:
                    payload = json.loads(
                        self.rfile.read(content_length).decode("utf-8")
                    )
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._write_error(
                        HTTPStatus.BAD_REQUEST, "Request body must be valid JSON"
                    )
                    return None
                if not isinstance(payload, dict):
                    self._write_error(
                        HTTPStatus.BAD_REQUEST, "Request body must be a JSON object"
                    )
                    return None
                return payload

            def _write_error(self, status: HTTPStatus, message: str) -> None:
                self._write_json(status, {"error": message})

            def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status.value)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return TeleinformationRequestHandler
