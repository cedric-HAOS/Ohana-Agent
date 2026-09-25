"""aiohttp listener running in its own thread for the synchronous Agent runtime."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Callable, Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from http import HTTPStatus
from threading import Thread
from typing import Any

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger

LOGGER = logging.getLogger(__name__)


class QuietAccessLogger(AbstractAccessLogger):
    """Log refused and failed requests, keep successful ones at DEBUG.

    With aiohttp every request was logged at INFO: Téléinformation frames,
    Katsuyu polling and Vision reads wrote about 3,800 lines per hour to the
    INFRA-01 journal, which truncated the daily Katsuyu log review.
    """

    def log(self, request, response, time: float) -> None:
        status = response.status
        level = (
            logging.WARNING
            if status >= 500
            else logging.INFO
            if status >= 400
            else logging.DEBUG
        )
        if not self.logger.isEnabledFor(level):
            return
        # The path only: query strings may carry identifiers or tokens.
        self.logger.log(
            level,
            '%s "%s %s" %s %.3fs',
            request.remote,
            request.method,
            request.path,
            status,
            time,
        )


_WRITE_BUFFER_BYTES = 256 * 1024
_SHUTDOWN_TIMEOUT_SECONDS = 3.0


def json_response(
    status: HTTPStatus,
    payload: object,
    *,
    compact: bool = True,
) -> web.Response:
    """Serialize one JSON document exactly like the former http.server handlers."""
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")  # type: ignore[union-attr]

    content = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":") if compact else None,
    ).encode("utf-8")
    return web.Response(
        status=status,
        body=content,
        content_type="application/json",
        charset="utf-8",
    )


class ThreadedHTTPListener:
    """Serve one aiohttp application from a dedicated event-loop thread.

    Handlers run on the listener loop; blocking Agent services must go through
    :meth:`run_blocking`, which uses the listener's own worker threads.
    """

    thread_name = "ohana-agent-http"
    server_header = "Ohana-Agent"
    max_workers = 16

    def __init__(self, *, host: str, port: int, logger: logging.Logger) -> None:
        self.host = host
        self.port = port
        self._logger = logger
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._thread: Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def address(self) -> tuple[str, int] | None:
        if self._runner is None or not self._runner.addresses:
            return None

        host, port = self._runner.addresses[0][:2]
        return str(host), int(port)

    def build_application(self) -> web.Application:
        raise NotImplementedError

    def ssl_context(self) -> ssl.SSLContext | None:
        return None

    def start(self) -> None:
        """Bind the socket, then serve in the background; bind errors are raised."""
        if self.running:
            return

        ssl_context = self.ssl_context()
        loop = asyncio.new_event_loop()
        executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix=f"{self.thread_name}-worker",
        )
        loop.set_default_executor(executor)
        ready: Future[web.AppRunner] = Future()
        thread = Thread(
            target=self._serve,
            args=(loop, executor, ssl_context, ready),
            name=self.thread_name,
            daemon=True,
        )
        thread.start()

        try:
            self._runner = ready.result()
        except BaseException:
            thread.join(timeout=5)
            raise

        self._loop = loop
        self._thread = thread

    def stop(self) -> None:
        """Stop accepting requests and release the socket."""
        if self._loop is not None and self._thread is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=_SHUTDOWN_TIMEOUT_SECONDS + 2)

        self._loop = None
        self._runner = None
        self._thread = None

    def _serve(
        self,
        loop: asyncio.AbstractEventLoop,
        executor: ThreadPoolExecutor,
        ssl_context: ssl.SSLContext | None,
        ready: Future[web.AppRunner],
    ) -> None:
        asyncio.set_event_loop(loop)
        runner: web.AppRunner | None = None

        try:
            application = self.build_application()
            application.on_response_prepare.append(self._set_server_header)
            runner = web.AppRunner(
                application,
                handle_signals=False,
                access_log=self._logger,
                access_log_class=QuietAccessLogger,
                shutdown_timeout=_SHUTDOWN_TIMEOUT_SECONDS,
            )
            loop.run_until_complete(runner.setup())
            loop.run_until_complete(
                web.TCPSite(
                    runner, self.host, self.port, ssl_context=ssl_context
                ).start()
            )
        except BaseException as error:
            if runner is not None:
                loop.run_until_complete(runner.cleanup())
            self._close_loop(loop, executor)
            ready.set_exception(error)
            return

        ready.set_result(runner)

        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(runner.cleanup())
            self._close_loop(loop, executor)

    @staticmethod
    def _close_loop(
        loop: asyncio.AbstractEventLoop,
        executor: ThreadPoolExecutor,
    ) -> None:
        loop.close()
        executor.shutdown(wait=False, cancel_futures=True)

    async def _set_server_header(
        self,
        _: web.Request,
        response: web.StreamResponse,
    ) -> None:
        response.headers["Server"] = self.server_header

    @staticmethod
    async def run_blocking[T](operation: Callable[[], T]) -> T:
        """Run one synchronous Agent operation off the event loop."""
        return await asyncio.get_running_loop().run_in_executor(None, operation)


class BlockingResponseWriter:
    """File-like writer letting a worker thread stream into an aiohttp response."""

    def __init__(
        self,
        response: web.StreamResponse,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._response = response
        self._loop = loop
        self._buffer = bytearray()

    def write(self, data: bytes) -> int:
        self._buffer += data

        if len(self._buffer) >= _WRITE_BUFFER_BYTES:
            self.flush()

        return len(data)

    def flush(self) -> None:
        if not self._buffer:
            return

        chunk = bytes(self._buffer)
        self._buffer.clear()
        call_on_loop(self._loop, self._response.write(chunk))


class BlockingRequestReader:
    """File-like reader exposing exactly one declared request body to a thread."""

    def __init__(
        self,
        request: web.Request,
        loop: asyncio.AbstractEventLoop,
        size_bytes: int,
    ) -> None:
        self._content = request.content
        self._loop = loop
        self.remaining = size_bytes

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""

        requested = self.remaining if size < 0 else min(size, self.remaining)
        chunk = call_on_loop(self._loop, self._content.read(requested))
        self.remaining -= len(chunk)
        return chunk


def call_on_loop[T](
    loop: asyncio.AbstractEventLoop,
    coroutine: Coroutine[Any, Any, T],
) -> T:
    """Run one coroutine on ``loop`` from a worker thread and wait for it."""
    return asyncio.run_coroutine_threadsafe(coroutine, loop).result()
