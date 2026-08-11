"""Programmatic and secret-safe rclone iCloud configuration."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RcloneICloudConfigurationError(RuntimeError):
    """Raised when rclone cannot establish an iCloud session."""


@dataclass(slots=True)
class _PendingConfiguration:
    apple_id: str
    password: str
    state: str
    operation: str
    expires_at: float


class RcloneICloudConfigurator:
    """Drive rclone's non-interactive configuration protocol."""

    def __init__(
        self,
        *,
        binary: str,
        config_path: str,
        remote_name: str,
        runner: Any = subprocess.run,
        clock: Any = time.monotonic,
    ) -> None:
        self.binary = binary
        self.config_path = Path(config_path)
        self.remote_name = remote_name
        self._runner = runner
        self._clock = clock
        self._pending: _PendingConfiguration | None = None

    def status(self) -> dict[str, Any]:
        binary_available = Path(self.binary).is_file()
        configured = False
        if binary_available and self.config_path.is_file():
            result = self._runner(
                [
                    self.binary,
                    "listremotes",
                    "--config",
                    str(self.config_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            configured = (
                result.returncode == 0
                and f"{self.remote_name}:" in result.stdout.splitlines()
            )
        pending = self._pending
        requires_two_factor = bool(
            pending is not None and pending.expires_at > self._clock()
        )
        return {
            "binary_available": binary_available,
            "configured": configured,
            "requires_two_factor": requires_two_factor,
            "remote_name": self.remote_name,
        }

    def connect(
        self,
        *,
        apple_id: str | None = None,
        password: str | None = None,
        two_factor_code: str | None = None,
    ) -> dict[str, Any]:
        if not Path(self.binary).is_file():
            raise RcloneICloudConfigurationError(
                f"rclone is not installed at {self.binary}."
            )
        if two_factor_code:
            pending = self._pending
            if pending is None or pending.expires_at <= self._clock():
                self._pending = None
                raise RcloneICloudConfigurationError(
                    "The iCloud authentication session expired; start again."
                )
            response = self._continue(
                pending,
                result=two_factor_code.strip(),
            )
        else:
            normalized_apple_id = (apple_id or "").strip()
            if not normalized_apple_id or not password:
                raise RcloneICloudConfigurationError(
                    "Apple ID and Apple password are required."
                )
            operation = "update" if self.status()["configured"] else "create"
            response = self._invoke(
                normalized_apple_id,
                password,
                operation=operation,
            )
            pending = _PendingConfiguration(
                apple_id=normalized_apple_id,
                password=password,
                state="",
                operation=operation,
                expires_at=self._clock() + 300,
            )

        for _index in range(10):
            state = response.get("State", "")
            if not state:
                self._pending = None
                self._secure_config()
                return {
                    **self.status(),
                    "connected": True,
                    "message": "Connexion iCloud configurée.",
                }
            option = response.get("Option", {})
            option_name = option.get("Name") if isinstance(option, dict) else None
            pending.state = str(state)
            pending.expires_at = self._clock() + 300
            if option_name == "config_2fa":
                self._pending = pending
                return {
                    **self.status(),
                    "connected": False,
                    "requires_two_factor": True,
                    "message": "Saisissez le code 2FA envoyé par Apple.",
                }
            default = option.get("Default") if isinstance(option, dict) else None
            if default is None:
                raise RcloneICloudConfigurationError(
                    f"rclone requested unsupported option {option_name!r}."
                )
            response = self._continue(pending, result=str(default))
        raise RcloneICloudConfigurationError(
            "rclone did not complete iCloud configuration."
        )

    def _invoke(
        self,
        apple_id: str,
        password: str,
        *,
        operation: str,
    ) -> dict[str, Any]:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.binary,
            "config",
            operation,
            self.remote_name,
            *(["iclouddrive"] if operation == "create" else []),
            "service",
            "drive",
            "apple_id",
            apple_id,
            "password",
            password,
            "--config",
            str(self.config_path),
            "--non-interactive",
            "--obscure",
        ]
        return self._run(command)

    def _continue(
        self,
        pending: _PendingConfiguration,
        *,
        result: str,
    ) -> dict[str, Any]:
        command = [
            self.binary,
            "config",
            pending.operation,
            self.remote_name,
            *(["iclouddrive"] if pending.operation == "create" else []),
            "service",
            "drive",
            "apple_id",
            pending.apple_id,
            "password",
            pending.password,
            "--config",
            str(self.config_path),
            "--non-interactive",
            "--obscure",
            "--continue",
            "--state",
            pending.state,
            "--result",
            result,
        ]
        return self._run(command)

    def _run(self, command: list[str]) -> dict[str, Any]:
        result = self._runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "RCLONE_CONFIG_PASS": ""},
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown rclone error").strip()
            for secret_name in ("apple_id", "password"):
                if secret_name in command:
                    index = command.index(secret_name) + 1
                    if index < len(command) and command[index]:
                        detail = detail.replace(command[index], "***")
            raise RcloneICloudConfigurationError(
                f"Unable to configure iCloud: {detail[:500]}"
            )
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as error:
            raise RcloneICloudConfigurationError(
                "rclone returned an invalid configuration response."
            ) from error
        if not isinstance(payload, dict):
            raise RcloneICloudConfigurationError(
                "rclone returned an invalid configuration response."
            )
        return payload

    def _secure_config(self) -> None:
        if self.config_path.exists():
            self.config_path.chmod(0o600)
