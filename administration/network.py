"""NetworkManager administration through the installed privileged helper."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from administration.models import (
    AgentNetworkChange,
    AgentNetworkChangeRequest,
    AgentNetworkState,
)


class NetworkAdministrationError(RuntimeError):
    """Raised when the privileged network helper rejects an operation."""


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class NetworkManagerRepository:
    """Read and update the host network through one restricted root helper."""

    def __init__(
        self,
        *,
        helper_path: Path = Path("/usr/local/sbin/ohana-network-helper"),
        sudo_path: Path = Path("/usr/bin/sudo"),
        rollback_seconds: int = 90,
        runner: CommandRunner = subprocess.run,
    ) -> None:
        self.helper_path = helper_path
        self.sudo_path = sudo_path
        self.rollback_seconds = rollback_seconds
        self.runner = runner

    def read(self) -> AgentNetworkState:
        """Return the active NetworkManager IPv4 configuration."""
        return AgentNetworkState.model_validate(self._execute(("status",)))

    def apply(self, payload: dict[str, Any]) -> AgentNetworkChange:
        """Apply a candidate configuration with an automatic rollback timer."""
        request = AgentNetworkChangeRequest.model_validate(payload)
        command = (
            "apply",
            "--rollback-seconds",
            str(request.rollback_seconds or self.rollback_seconds),
        )
        result = self._execute(
            command,
            request.settings.model_dump(mode="json"),
        )
        return AgentNetworkChange.model_validate(result)

    def confirm(self, transaction_id: str) -> AgentNetworkState:
        """Confirm a pending network change and cancel its rollback."""
        return AgentNetworkState.model_validate(
            self._execute(("confirm", transaction_id))
        )

    def rollback(self, transaction_id: str) -> AgentNetworkState:
        """Immediately restore the configuration saved for one transaction."""
        return AgentNetworkState.model_validate(
            self._execute(("rollback", transaction_id))
        )

    def _execute(
        self,
        arguments: Sequence[str],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        command = [
            self.sudo_path.as_posix(),
            "-n",
            self.helper_path.as_posix(),
            *arguments,
        ]
        input_data = None

        if payload is not None:
            input_data = json.dumps(payload, separators=(",", ":"))

        try:
            result = self.runner(
                command,
                input=input_data,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise NetworkAdministrationError(
                f"Unable to execute the network helper: {error}"
            ) from error

        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise NetworkAdministrationError(
                detail or "The network helper rejected the operation"
            )

        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise NetworkAdministrationError(
                "The network helper returned invalid JSON"
            ) from error

        if not isinstance(response, dict):
            raise NetworkAdministrationError(
                "The network helper returned an invalid document"
            )

        return response
