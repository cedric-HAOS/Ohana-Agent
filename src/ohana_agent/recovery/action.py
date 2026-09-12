"""Recovery actions for Ohana-Agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ohana_agent.recovery.result import RecoveryResult


class RecoveryAction(Protocol):
    """Protocol implemented by recovery actions."""

    name: str
    source: str

    def execute(self) -> RecoveryResult:
        """Execute the recovery action."""
        ...


@dataclass(frozen=True)
class NoopRecoveryAction:
    """Recovery action that does nothing successfully."""

    name: str
    source: str
    message: str = "No operation performed."

    def execute(self) -> RecoveryResult:
        """Execute the no-op recovery action."""
        return RecoveryResult(
            success=True,
            action=self.name,
            source=self.source,
            message=self.message,
        )
