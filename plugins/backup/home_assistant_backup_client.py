"""Authenticated Home Assistant backup client using the public APIs."""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import aiohttp

from plugins.backup.backup_config import BackupTarget


class HomeAssistantBackupError(RuntimeError):
    """Raised when Home Assistant cannot complete a backup operation."""


@dataclass(frozen=True, slots=True)
class HomeAssistantBackup:
    """Backup identity returned by Home Assistant."""

    slug: str
    name: str | None = None
    agent_id: str = "hassio.local"


@dataclass(slots=True)
class BackupDownload:
    """Open backup archive response and its exact byte length."""

    stream: BinaryIO
    size_bytes: int


class HomeAssistantBackupClient:
    """Create, list, download and delete HAOS backups through public APIs."""

    def __init__(self, target: BackupTarget, token: str) -> None:
        self._target = target
        self._token = token

    def run_pre_backup_action(self) -> None:
        action = self._target.pre_backup_action
        if action is None:
            return
        self._request_json_value(
            "POST",
            f"/api/services/{action.domain}/{action.service}",
            payload=action.data,
        )

    def list_backups(self) -> tuple[HomeAssistantBackup, ...]:
        response = self._run(self._command("backup/info"))
        backups = response.get("backups", []) if isinstance(response, dict) else []
        if not isinstance(backups, list):
            raise HomeAssistantBackupError("Home Assistant returned invalid backups.")
        parsed: list[HomeAssistantBackup] = []
        for item in backups:
            if not isinstance(item, dict):
                continue
            backup_id = item.get("backup_id")
            name = item.get("name")
            agents = item.get("agents", {})
            if not isinstance(backup_id, str) or not backup_id.strip():
                continue
            agent_id = self._local_agent_id(agents)
            if agent_id is None:
                continue
            parsed.append(
                HomeAssistantBackup(
                    slug=backup_id.strip(),
                    name=name if isinstance(name, str) else None,
                    agent_id=agent_id,
                )
            )
        return tuple(parsed)

    def create_full_backup(self, name: str, *, password: str) -> HomeAssistantBackup:
        return self._run(self._create_full_backup(name, password=password))

    @contextmanager
    def download(self, slug: str) -> Iterator[BackupDownload]:
        agent_id = self._backup_agent_id(slug)
        query = urlencode({"agent_id": agent_id})
        response = self._open(
            "GET",
            f"/api/backup/download/{quote(slug, safe='')}?{query}",
        )
        try:
            content_length = response.headers.get("Content-Length")
            try:
                size_bytes = int(content_length) if content_length else 0
            except ValueError as error:
                raise HomeAssistantBackupError(
                    "Home Assistant returned an invalid backup Content-Length."
                ) from error
            if size_bytes <= 0:
                raise HomeAssistantBackupError(
                    "Home Assistant did not provide the backup size; refusing an "
                    "unbounded upload that could spill onto the INFRA-01 SD card."
                )
            yield BackupDownload(stream=response, size_bytes=size_bytes)
        finally:
            response.close()

    def delete(self, slug: str) -> None:
        self._run(self._command("backup/delete", backup_id=slug))

    async def _create_full_backup(
        self,
        name: str,
        *,
        password: str,
    ) -> HomeAssistantBackup:
        async with self._session() as session:
            async with session.ws_connect(
                self._websocket_url(),
                ssl=self._ssl_parameter(),
            ) as websocket:
                await self._authenticate(websocket)
                await websocket.send_json({"id": 1, "type": "backup/subscribe_events"})
                await self._wait_result(websocket, 1)
                await websocket.send_json({"id": 2, "type": "backup/agents/info"})
                agents_result = await self._wait_result(websocket, 2)
                agent_id = self._select_local_agent(agents_result)
                await websocket.send_json(
                    {
                        "id": 3,
                        "type": "backup/generate",
                        "agent_ids": [agent_id],
                        "include_all_addons": True,
                        "include_database": True,
                        "include_folders": ["share", "addons/local", "ssl", "media"],
                        "include_homeassistant": True,
                        "name": name,
                        "password": password,
                    }
                )
                await self._wait_result(websocket, 3)
                await self._wait_backup_completion(websocket)
                await websocket.send_json({"id": 4, "type": "backup/info"})
                info = await self._wait_result(websocket, 4)
        for item in info.get("backups", []) if isinstance(info, dict) else []:
            if isinstance(item, dict) and item.get("name") == name:
                backup_id = item.get("backup_id")
                if isinstance(backup_id, str) and backup_id:
                    return HomeAssistantBackup(
                        slug=backup_id,
                        name=name,
                        agent_id=agent_id,
                    )
        raise HomeAssistantBackupError(
            "Home Assistant completed the backup but did not return its identifier."
        )

    async def _command(self, command_type: str, **values: Any) -> Any:
        async with self._session() as session:
            async with session.ws_connect(
                self._websocket_url(),
                ssl=self._ssl_parameter(),
            ) as websocket:
                await self._authenticate(websocket)
                await websocket.send_json({"id": 1, "type": command_type, **values})
                return await self._wait_result(websocket, 1)

    def _run(self, awaitable: Any) -> Any:
        try:
            return asyncio.run(awaitable)
        except HomeAssistantBackupError:
            raise
        except (TimeoutError, aiohttp.ClientError, OSError) as error:
            raise HomeAssistantBackupError(
                f"Unable to reach Home Assistant at {self._target.url}: {error}"
            ) from error

    def _session(self) -> aiohttp.ClientSession:
        timeout = aiohttp.ClientTimeout(total=self._target.timeout)
        return aiohttp.ClientSession(timeout=timeout)

    async def _authenticate(self, websocket: aiohttp.ClientWebSocketResponse) -> None:
        required = await websocket.receive_json()
        if required.get("type") != "auth_required":
            raise HomeAssistantBackupError("Home Assistant rejected WebSocket setup.")
        await websocket.send_json({"type": "auth", "access_token": self._token})
        response = await websocket.receive_json()
        if response.get("type") != "auth_ok":
            raise HomeAssistantBackupError("Home Assistant rejected the access token.")

    @staticmethod
    async def _wait_result(
        websocket: aiohttp.ClientWebSocketResponse,
        identifier: int,
    ) -> Any:
        while True:
            message = await websocket.receive_json()
            if message.get("type") != "result" or message.get("id") != identifier:
                continue
            if not message.get("success"):
                error = message.get("error", {})
                detail = error.get("message") if isinstance(error, dict) else error
                raise HomeAssistantBackupError(
                    str(detail or "Home Assistant command failed.")
                )
            return message.get("result")

    @staticmethod
    async def _wait_backup_completion(
        websocket: aiohttp.ClientWebSocketResponse,
    ) -> None:
        while True:
            message = await websocket.receive_json()
            if message.get("type") != "event" or message.get("id") != 1:
                continue
            event = message.get("event", {})
            if (
                not isinstance(event, dict)
                or event.get("manager_state") != "create_backup"
            ):
                continue
            state = event.get("state")
            if state == "completed":
                return
            if state == "failed":
                reason = event.get("reason") or "unknown error"
                raise HomeAssistantBackupError(
                    f"Home Assistant backup failed: {reason}."
                )

    @staticmethod
    def _select_local_agent(result: Any) -> str:
        agents = result.get("agents", []) if isinstance(result, dict) else []
        identifiers = [
            item.get("agent_id")
            for item in agents
            if isinstance(item, dict) and isinstance(item.get("agent_id"), str)
        ]
        for identifier in identifiers:
            if identifier == "hassio.local":
                return identifier
        for identifier in identifiers:
            if identifier.startswith("hassio."):
                return identifier
        raise HomeAssistantBackupError(
            "Home Assistant exposes no local HAOS backup agent."
        )

    @staticmethod
    def _local_agent_id(agents: Any) -> str | None:
        if not isinstance(agents, dict):
            return None
        if "hassio.local" in agents:
            return "hassio.local"
        return next((key for key in agents if key.startswith("hassio.")), None)

    def _backup_agent_id(self, slug: str) -> str:
        for backup in self.list_backups():
            if backup.slug == slug:
                return backup.agent_id
        raise HomeAssistantBackupError(f"Home Assistant backup {slug!r} was not found.")

    def _websocket_url(self) -> str:
        if self._target.url.startswith("https://"):
            return f"wss://{self._target.url.removeprefix('https://')}/api/websocket"
        return f"ws://{self._target.url.removeprefix('http://')}/api/websocket"

    def _ssl_parameter(self) -> ssl.SSLContext | bool:
        if not self._target.url.startswith("https://"):
            return True
        if self._target.verify_tls:
            return True
        return False

    def _request_json_value(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        response = self._open(method, path, payload=payload)
        try:
            raw = response.read()
        finally:
            response.close()
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HomeAssistantBackupError(
                "Home Assistant returned an invalid JSON response."
            ) from error

    def _open(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self._target.url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        context = None
        if request.full_url.startswith("https://") and not self._target.verify_tls:
            context = ssl._create_unverified_context()  # noqa: S323
        try:
            return urlopen(request, timeout=self._target.timeout, context=context)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise HomeAssistantBackupError(
                f"Home Assistant returned HTTP {error.code}: {detail[:500]}"
            ) from error
        except (TimeoutError, URLError) as error:
            raise HomeAssistantBackupError(
                f"Unable to reach Home Assistant at {self._target.url}: {error}"
            ) from error
