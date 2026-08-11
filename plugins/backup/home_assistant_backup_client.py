"""Authenticated Home Assistant Supervisor backup client."""

from __future__ import annotations

import json
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from plugins.backup.backup_config import BackupTarget


class HomeAssistantBackupError(RuntimeError):
    """Raised when Home Assistant cannot complete a backup operation."""


@dataclass(frozen=True, slots=True)
class HomeAssistantBackup:
    """Backup identity returned by Home Assistant."""

    slug: str
    name: str | None = None


@dataclass(slots=True)
class BackupDownload:
    """Open backup archive response and its exact byte length."""

    stream: BinaryIO
    size_bytes: int


class HomeAssistantBackupClient:
    """Create, list, download and delete HAOS full backups."""

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
        response = self._request_json("GET", "/api/hassio/backups")
        data = self._response_data(response)
        backups = data.get("backups", [])
        if not isinstance(backups, list):
            raise HomeAssistantBackupError("Home Assistant returned invalid backups.")

        parsed: list[HomeAssistantBackup] = []
        for item in backups:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug")
            name = item.get("name")
            if isinstance(slug, str) and slug.strip():
                parsed.append(
                    HomeAssistantBackup(
                        slug=slug.strip(),
                        name=name if isinstance(name, str) else None,
                    )
                )
        return tuple(parsed)

    def create_full_backup(self, name: str, *, password: str) -> HomeAssistantBackup:
        response = self._request_json(
            "POST",
            "/api/hassio/backups/new/full",
            payload={"name": name, "password": password, "background": False},
        )
        data = self._response_data(response)
        slug = data.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            raise HomeAssistantBackupError(
                "Home Assistant did not return the completed backup slug."
            )
        return HomeAssistantBackup(slug=slug.strip(), name=name)

    @contextmanager
    def download(self, slug: str) -> Iterator[BackupDownload]:
        response = self._open("GET", f"/api/hassio/backups/{slug}/download")
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
        self._request_json("DELETE", f"/api/hassio/backups/{slug}")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        parsed = self._request_json_value(method, path, payload=payload)
        if not isinstance(parsed, dict):
            raise HomeAssistantBackupError(
                "Home Assistant returned an unexpected JSON response."
            )
        if parsed.get("result") == "error":
            message = parsed.get("message") or "Supervisor backup request failed."
            raise HomeAssistantBackupError(str(message))
        return parsed

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
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HomeAssistantBackupError(
                "Home Assistant returned an invalid JSON response."
            ) from error
        return parsed

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
            return urlopen(
                request,
                timeout=self._target.timeout,
                context=context,
            )
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise HomeAssistantBackupError(
                f"Home Assistant returned HTTP {error.code}: {detail[:500]}"
            ) from error
        except (TimeoutError, URLError) as error:
            raise HomeAssistantBackupError(
                f"Unable to reach Home Assistant at {self._target.url}: {error}"
            ) from error

    @staticmethod
    def _response_data(response: dict[str, Any]) -> dict[str, Any]:
        data = response.get("data", response)
        if not isinstance(data, dict):
            raise HomeAssistantBackupError("Home Assistant returned invalid data.")
        return data
