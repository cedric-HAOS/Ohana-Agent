"""Freebox WireGuard server check with retry support."""

from plugins.wireguard.wireguard_client import FreeboxWireGuardClient
from plugins.wireguard.wireguard_result import WireGuardCheckResult


class WireGuardCheck:
    """Check whether the WireGuard server exposed by a Freebox is started."""

    def __init__(self, client: FreeboxWireGuardClient | None = None) -> None:
        self._client = client or FreeboxWireGuardClient()

    def check(
        self,
        service_name: str,
        base_url: str,
        *,
        server_name: str = "wireguard",
        app_id: str,
        app_version: str,
        app_token: str | None,
        timeout: float = 3.0,
        retries: int = 1,
        verify_tls: bool = False,
    ) -> WireGuardCheckResult:
        """Query Freebox OS until the server is healthy or retries are exhausted."""
        if retries < 0:
            raise ValueError("retries must be greater than or equal to zero.")

        normalized_service_name = service_name.strip()
        normalized_base_url = base_url.strip()
        normalized_server_name = server_name.strip()

        if not normalized_service_name:
            raise ValueError("service_name must not be empty.")

        if not normalized_base_url:
            raise ValueError("base_url must not be empty.")

        if not normalized_server_name:
            raise ValueError("server_name must not be empty.")

        last_response = None
        attempts = 0

        for _attempt in range(retries + 1):
            attempts += 1
            last_response = self._client.query(
                normalized_base_url,
                app_id=app_id,
                app_version=app_version,
                app_token=app_token,
                server_name=normalized_server_name,
                timeout=timeout,
                verify_tls=verify_tls,
            )

            if last_response.success:
                break

        if last_response is None:
            raise RuntimeError("WireGuard check did not execute any request.")

        return WireGuardCheckResult(
            service_name=normalized_service_name,
            base_url=normalized_base_url,
            server_name=normalized_server_name,
            healthy=last_response.success,
            state=last_response.state,
            connection_count=last_response.connection_count,
            authenticated_connection_count=(
                last_response.authenticated_connection_count
            ),
            attempts=attempts,
            error=last_response.error,
        )
