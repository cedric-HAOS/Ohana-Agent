"""Clients for Z-Wave JS Server and legacy Z-Wave JS UI health checks."""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import Awaitable, Callable
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from plugins.zwave.zwave_result import ZWaveHealthResult

WebSocketQuery = Callable[[str, float, bool], Awaitable[ZWaveHealthResult]]


def _agent_version() -> str:
    """Return the installed Agent version advertised to Z-Wave JS Server."""
    try:
        return package_version("ohana-agent")
    except PackageNotFoundError:
        return "1.8.0"


class ZWaveHealthClient:
    """Query a Z-Wave JS Server WebSocket or legacy HTTP health endpoint."""

    def __init__(self, websocket_query: WebSocketQuery | None = None) -> None:
        self._websocket_query = websocket_query or self._query_websocket

    def query(
        self,
        url: str,
        *,
        timeout: float = 3.0,
        verify_tls: bool = True,
    ) -> ZWaveHealthResult:
        """Return the health reported by the configured Z-Wave endpoint."""
        scheme = urlsplit(url).scheme.lower()

        if scheme in {"ws", "wss"}:
            try:
                return asyncio.run(
                    self._websocket_query(
                        url,
                        timeout,
                        verify_tls,
                    )
                )
            except (RuntimeError, OSError, TimeoutError, ValueError) as error:
                return ZWaveHealthResult(
                    url=url,
                    healthy=False,
                    error=str(error),
                )

        if scheme in {"http", "https"}:
            return self._query_http(
                url,
                timeout=timeout,
                verify_tls=verify_tls,
            )

        return ZWaveHealthResult(
            url=url,
            healthy=False,
            error=f"Unsupported Z-Wave endpoint scheme: {scheme or 'missing'}.",
        )

    async def _query_websocket(
        self,
        url: str,
        timeout: float,
        verify_tls: bool,
    ) -> ZWaveHealthResult:
        """Connect through the official Z-Wave JS Server protocol."""
        try:
            from aiohttp import ClientSession, ClientTimeout, TCPConnector
            from zwave_js_server.client import Client
        except ImportError as error:
            return ZWaveHealthResult(
                url=url,
                healthy=False,
                error=(
                    f"The zwave-js-server-python dependency is unavailable: {error}"
                ),
            )

        connector = None

        if url.lower().startswith("wss://") and not verify_tls:
            connector = TCPConnector(ssl=False)

        client = None
        listen_task: asyncio.Task[None] | None = None
        ready_task: asyncio.Task[bool] | None = None

        try:
            async with ClientSession(
                timeout=ClientTimeout(total=timeout),
                connector=connector,
            ) as session:
                client = Client(
                    url,
                    session,
                    additional_user_agent_components={
                        "ohana-agent": _agent_version(),
                    },
                )
                await asyncio.wait_for(
                    client.connect(),
                    timeout=timeout,
                )

                driver_ready = asyncio.Event()
                listen_task = asyncio.create_task(client.listen(driver_ready))
                ready_task = asyncio.create_task(driver_ready.wait())
                done, _pending = await asyncio.wait(
                    {ready_task, listen_task},
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if ready_task not in done or not driver_ready.is_set():
                    if listen_task in done:
                        error = listen_task.exception()
                        detail = (
                            str(error) if error is not None else "connection closed"
                        )
                    else:
                        detail = "driver initialization timed out"

                    return ZWaveHealthResult(
                        url=url,
                        healthy=False,
                        error=f"Z-Wave JS Server is unavailable: {detail}.",
                    )

                version = client.version
                driver = client.driver

                if version is None or driver is None:
                    return ZWaveHealthResult(
                        url=url,
                        healthy=False,
                        error="Z-Wave JS Server did not expose a ready driver.",
                    )

                return ZWaveHealthResult(
                    url=url,
                    healthy=True,
                    response="Z-Wave JS driver ready",
                    server_version=str(version.server_version),
                    driver_version=str(version.driver_version),
                    home_id=str(version.home_id),
                    node_count=len(driver.controller.nodes),
                )
        except Exception as error:  # Health probes must report failures as data.
            return ZWaveHealthResult(
                url=url,
                healthy=False,
                error=f"Z-Wave JS Server connection failed: {error}",
            )
        finally:
            if client is not None and client.connected:
                try:
                    await client.disconnect()
                except Exception:
                    pass

            if ready_task is not None and not ready_task.done():
                ready_task.cancel()
                await asyncio.gather(
                    ready_task,
                    return_exceptions=True,
                )

            if listen_task is not None and not listen_task.done():
                listen_task.cancel()
                await asyncio.gather(
                    listen_task,
                    return_exceptions=True,
                )

    @staticmethod
    def _query_http(
        url: str,
        *,
        timeout: float,
        verify_tls: bool,
    ) -> ZWaveHealthResult:
        """Query the legacy Z-Wave JS UI HTTP health endpoint."""
        request = Request(
            url,
            headers={
                "Accept": "text/plain, application/json",
                "User-Agent": "Ohana-Agent Z-Wave health check",
            },
        )
        context = None

        if url.lower().startswith("https://") and not verify_tls:
            context = ssl._create_unverified_context()

        try:
            with urlopen(request, timeout=timeout, context=context) as response:
                status_code = int(response.status)
                body = (
                    response.read(4096)
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                    .strip()
                )
                return ZWaveHealthResult(
                    url=url,
                    healthy=status_code == 200,
                    status_code=status_code,
                    response=body or None,
                    error=(
                        None
                        if status_code == 200
                        else f"Z-Wave health endpoint returned HTTP {status_code}."
                    ),
                )
        except HTTPError as error:
            body = (
                error.read(4096)
                .decode(
                    "utf-8",
                    errors="replace",
                )
                .strip()
            )
            return ZWaveHealthResult(
                url=url,
                healthy=False,
                status_code=error.code,
                response=body or None,
                error=f"Z-Wave health endpoint returned HTTP {error.code}.",
            )
        except (URLError, TimeoutError, OSError) as error:
            return ZWaveHealthResult(
                url=url,
                healthy=False,
                error=str(error),
            )
