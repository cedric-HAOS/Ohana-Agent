"""Authenticated client for the Freebox OS WireGuard server API."""

from __future__ import annotations

import hashlib
import hmac
import json
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class FreeboxWireGuardResponse:
    """Normalized Freebox WireGuard server state."""

    success: bool
    state: str | None = None
    connection_count: int | None = None
    authenticated_connection_count: int | None = None
    error: str | None = None


class FreeboxWireGuardClient:
    """Open a Freebox OS API session and inspect its WireGuard server."""

    def query(
        self,
        base_url: str,
        *,
        app_id: str,
        app_version: str,
        app_token: str | None,
        server_name: str = "wireguard",
        timeout: float = 3.0,
        verify_tls: bool = False,
    ) -> FreeboxWireGuardResponse:
        """Return the selected VPN server state reported by Freebox OS."""
        if not app_token:
            return FreeboxWireGuardResponse(
                success=False,
                error=(
                    "The Freebox app_token is not configured. Authorize "
                    "Ohana-Agent on the Freebox before enabling this plugin."
                ),
            )

        try:
            api_root = self._discover_api_root(
                base_url,
                timeout=timeout,
                verify_tls=verify_tls,
            )
            challenge_payload = self._request_json(
                "GET",
                urljoin(api_root, "login/"),
                timeout=timeout,
                verify_tls=verify_tls,
            )
            challenge = self._result_value(challenge_payload, "challenge")

            if not isinstance(challenge, str) or not challenge:
                return FreeboxWireGuardResponse(
                    success=False,
                    error="Freebox OS did not return an authentication challenge.",
                )

            password = hmac.new(
                app_token.encode("utf-8"),
                challenge.encode("utf-8"),
                hashlib.sha1,
            ).hexdigest()
            session_payload = self._request_json(
                "POST",
                urljoin(api_root, "login/session/"),
                body={
                    "app_id": app_id,
                    "app_version": app_version,
                    "password": password,
                },
                timeout=timeout,
                verify_tls=verify_tls,
            )
            session_token = self._result_value(
                session_payload,
                "session_token",
            )

            if not isinstance(session_token, str) or not session_token:
                return FreeboxWireGuardResponse(
                    success=False,
                    error=self._error_message(
                        session_payload,
                        "Unable to open a Freebox OS API session.",
                    ),
                )

            servers_payload = self._request_json(
                "GET",
                urljoin(api_root, "vpn/"),
                headers={"X-Fbx-App-Auth": session_token},
                timeout=timeout,
                verify_tls=verify_tls,
            )
            servers = servers_payload.get("result")

            if not servers_payload.get("success") or not isinstance(servers, list):
                return FreeboxWireGuardResponse(
                    success=False,
                    error=self._error_message(
                        servers_payload,
                        "Unable to read VPN servers from Freebox OS.",
                    ),
                )

            server = next(
                (
                    candidate
                    for candidate in servers
                    if isinstance(candidate, dict)
                    and candidate.get("name") == server_name
                ),
                None,
            )

            if server is None:
                return FreeboxWireGuardResponse(
                    success=False,
                    error=(
                        f"Freebox OS did not expose the VPN server {server_name!r}."
                    ),
                )

            state = server.get("state")
            normalized_state = state if isinstance(state, str) else None
            return FreeboxWireGuardResponse(
                success=normalized_state == "started",
                state=normalized_state,
                connection_count=self._optional_int(server.get("connection_count")),
                authenticated_connection_count=self._optional_int(
                    server.get("auth_connection_count")
                ),
                error=(
                    None
                    if normalized_state == "started"
                    else (
                        "The Freebox WireGuard server is not started"
                        + (
                            f" (state: {normalized_state})."
                            if normalized_state
                            else "."
                        )
                    )
                ),
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            return FreeboxWireGuardResponse(
                success=False,
                error=str(error),
            )

    def request_authorization(
        self,
        base_url: str,
        *,
        app_id: str,
        app_name: str,
        app_version: str,
        device_name: str,
        timeout: float = 5.0,
        verify_tls: bool = False,
    ) -> tuple[str, int, str]:
        """Request a new app token and return token, track id and API root."""
        api_root = self._discover_api_root(
            base_url,
            timeout=timeout,
            verify_tls=verify_tls,
        )
        payload = self._request_json(
            "POST",
            urljoin(api_root, "login/authorize/"),
            body={
                "app_id": app_id,
                "app_name": app_name,
                "app_version": app_version,
                "device_name": device_name,
            },
            timeout=timeout,
            verify_tls=verify_tls,
        )
        result = payload.get("result")

        if not payload.get("success") or not isinstance(result, dict):
            raise ValueError(
                self._error_message(
                    payload,
                    "Freebox application authorization failed.",
                )
            )

        app_token = result.get("app_token")
        track_id = result.get("track_id")

        if not isinstance(app_token, str) or not isinstance(track_id, int):
            raise ValueError("Freebox authorization returned an invalid response.")

        return app_token, track_id, api_root

    def authorization_status(
        self,
        api_root: str,
        track_id: int,
        *,
        timeout: float = 5.0,
        verify_tls: bool = False,
    ) -> str:
        """Return the authorization status for one track identifier."""
        payload = self._request_json(
            "GET",
            urljoin(api_root, f"login/authorize/{track_id}"),
            timeout=timeout,
            verify_tls=verify_tls,
        )
        status = self._result_value(payload, "status")

        if not isinstance(status, str):
            raise ValueError(
                self._error_message(
                    payload,
                    "Unable to read Freebox authorization status.",
                )
            )

        return status

    def _discover_api_root(
        self,
        base_url: str,
        *,
        timeout: float,
        verify_tls: bool,
    ) -> str:
        normalized_base_url = base_url.rstrip("/") + "/"
        payload = self._request_json(
            "GET",
            urljoin(normalized_base_url, "api_version"),
            timeout=timeout,
            verify_tls=verify_tls,
            wrapped=False,
        )
        api_version = payload.get("api_version")
        api_base_url = payload.get("api_base_url", "/api/")

        if not isinstance(api_version, str):
            raise ValueError("Freebox discovery did not return api_version.")

        if not isinstance(api_base_url, str):
            raise ValueError("Freebox discovery did not return api_base_url.")

        try:
            major_version = int(api_version.split(".", maxsplit=1)[0])
        except ValueError as error:
            raise ValueError(
                f"Unsupported Freebox API version: {api_version!r}."
            ) from error

        base_path = api_base_url.strip("/")
        return urljoin(
            normalized_base_url,
            f"{base_path}/v{major_version}/",
        )

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
        verify_tls: bool,
        wrapped: bool = True,
    ) -> dict[str, Any]:
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "Ohana-Agent Freebox WireGuard check",
            **(headers or {}),
        }
        encoded_body = None

        if body is not None:
            encoded_body = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        context = None

        if url.lower().startswith("https://") and not verify_tls:
            context = ssl._create_unverified_context()

        request = Request(
            url,
            data=encoded_body,
            headers=request_headers,
            method=method,
        )

        try:
            with urlopen(request, timeout=timeout, context=context) as response:
                raw = response.read(1_048_576).decode("utf-8")
        except HTTPError as error:
            raw = error.read(1_048_576).decode("utf-8", errors="replace")

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                raise ValueError(f"Freebox OS returned HTTP {error.code}.") from error

            raise ValueError(
                self._error_message(
                    payload,
                    f"Freebox OS returned HTTP {error.code}.",
                )
            ) from error

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("Freebox OS returned invalid JSON.") from error

        if not isinstance(payload, dict):
            raise ValueError("Freebox OS returned an invalid response object.")

        if wrapped and payload.get("success") is False:
            raise ValueError(
                self._error_message(payload, "Freebox OS API request failed.")
            )

        return payload

    @staticmethod
    def _result_value(payload: dict[str, Any], key: str) -> Any:
        result = payload.get("result")

        if not payload.get("success") or not isinstance(result, dict):
            return None

        return result.get(key)

    @staticmethod
    def _error_message(payload: dict[str, Any], fallback: str) -> str:
        message = payload.get("msg")
        error_code = payload.get("error_code")

        if isinstance(message, str) and message:
            return message

        if isinstance(error_code, str) and error_code:
            return f"{fallback} ({error_code})"

        return fallback

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None

        if isinstance(value, int):
            return value

        return None
