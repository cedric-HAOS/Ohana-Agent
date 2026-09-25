"""Dedicated HTTP endpoint receiving frames directly from teleinfo2mqtt."""

from __future__ import annotations

import hmac
import json
import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web

from ohana_agent.core.http_listener import ThreadedHTTPListener, json_response
from ohana_agent.plugins.teleinformation.frame_store import (
    TeleinformationFrameStore,
)

LOGGER = logging.getLogger(__name__)
_MAXIMUM_REQUEST_BYTES = 131_072
FRAMES_PATH = "/v1/teleinformation/frames"


class _Rejected(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _error_response(status: HTTPStatus, message: str) -> web.Response:
    return json_response(status, {"error": message}, compact=False)


class TeleinformationIngestionHTTPServer(ThreadedHTTPListener):
    """Small authenticated receiver isolated from the administration API."""

    thread_name = "ohana-agent-teleinformation-ingestion"
    server_header = "Ohana-Agent-Teleinformation/1"

    def __init__(
        self,
        *,
        frame_store: TeleinformationFrameStore,
        token: str,
        host: str = "0.0.0.0",
        port: int = 8770,
    ) -> None:
        super().__init__(host=host, port=port, logger=LOGGER)
        self.frame_store = frame_store
        self._token = self._normalize_token(token)

    def start(self) -> None:
        if self.running:
            return
        super().start()
        LOGGER.info(
            "Téléinformation ingestion listening on http://%s:%s", *self.address
        )

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

    def build_application(self) -> web.Application:
        application = web.Application(client_max_size=_MAXIMUM_REQUEST_BYTES + 1)
        application.router.add_route("*", "/{path:.*}", self._dispatch)
        return application

    async def _dispatch(self, request: web.Request) -> web.Response:
        if request.method != "POST":
            return _error_response(HTTPStatus.NOT_IMPLEMENTED, "Unsupported method")
        if request.raw_path.split("?", 1)[0] != FRAMES_PATH:
            return _error_response(HTTPStatus.NOT_FOUND, "Endpoint not found")

        try:
            self._authorize(request)
            payload = await self._read_json(request)
            stored = await self.run_blocking(lambda: self._store(payload))
        except _Rejected as rejection:
            return _error_response(rejection.status, rejection.message)

        return json_response(
            HTTPStatus.ACCEPTED,
            {
                "accepted": True,
                "source": stored.source,
                "meter_id": stored.meter_id,
                "received_at": stored.received_at.isoformat(),
            },
            compact=False,
        )

    def _authorize(self, request: web.Request) -> None:
        authorization = request.headers.get("Authorization", "")
        prefix = "Bearer "
        supplied = (
            authorization.removeprefix(prefix)
            if authorization.startswith(prefix)
            else ""
        )
        if not supplied or not hmac.compare_digest(supplied, self._token):
            raise _Rejected(
                HTTPStatus.UNAUTHORIZED,
                "A valid Téléinformation ingestion token is required",
            )

    @staticmethod
    async def _read_json(request: web.Request) -> dict[str, Any]:
        content_length = request.content_length or 0
        if content_length <= 0 or content_length > _MAXIMUM_REQUEST_BYTES:
            raise _Rejected(HTTPStatus.BAD_REQUEST, "Invalid request body size")
        try:
            payload = json.loads((await request.read()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _Rejected(
                HTTPStatus.BAD_REQUEST, "Request body must be valid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise _Rejected(
                HTTPStatus.BAD_REQUEST, "Request body must be a JSON object"
            )
        return payload

    def _store(self, payload: dict[str, Any]) -> Any:
        try:
            if payload.get("schema_version") != 1:
                raise ValueError("schema_version must be 1.")
            frame = payload.get("frame")
            if not isinstance(frame, dict):
                raise ValueError("frame must be a JSON object.")
            return self.frame_store.put(
                source=payload.get("source"),
                meter_id=payload.get("meter_id"),
                frame=frame,
            )
        except ValueError as error:
            raise _Rejected(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
