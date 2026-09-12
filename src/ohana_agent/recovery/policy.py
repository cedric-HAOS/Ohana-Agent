"""Recovery policies for Ohana-Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ohana_agent.observation.health.monitor import HealthResult, HealthStatus
from ohana_agent.recovery.action import RecoveryAction
from ohana_agent.recovery.result import RecoveryResult


@dataclass(frozen=True)
class RecoveryHistory:
    """Represents the history of recovery attempts for one source."""

    source: str
    attempts: int = 0
    last_action: str | None = None
    last_success: bool | None = None
    results: tuple[RecoveryResult, ...] = field(default_factory=tuple)

    def record(self, result: RecoveryResult) -> RecoveryHistory:
        """Return a new history with an additional recovery result."""
        return RecoveryHistory(
            source=self.source,
            attempts=self.attempts + 1,
            last_action=result.action,
            last_success=result.success,
            results=(*self.results, result),
        )


class RecoveryPolicy(Protocol):
    """Protocol implemented by recovery policies."""

    @property
    def priority(self) -> int:
        """Return the policy priority."""
        ...

    def applies_to(self, result: HealthResult) -> bool:
        """Return whether this policy applies to a health result."""
        ...

    def next_action(self, history: RecoveryHistory) -> RecoveryAction | None:
        """Return the next recovery action to execute."""
        ...


class SequentialRecoveryPolicy:
    """Recovery policy executing actions in sequence."""

    def __init__(
        self,
        source: str,
        actions: list[RecoveryAction],
        statuses: set[HealthStatus] | None = None,
        priority: int = 0,
        stop_on_success: bool = True,
    ) -> None:
        self.source = source
        self.actions = actions
        self.statuses = statuses or {HealthStatus.DEGRADED, HealthStatus.UNHEALTHY}
        self._priority = priority
        self.stop_on_success = stop_on_success

    @property
    def priority(self) -> int:
        """Return the policy priority."""
        return self._priority

    def applies_to(self, result: HealthResult) -> bool:
        """Return whether this policy applies to a health result."""
        return result.name == self.source and result.status in self.statuses

    def next_action(self, history: RecoveryHistory) -> RecoveryAction | None:
        """Return the next action to execute from the sequence."""
        if history.source != self.source:
            return None

        if self.stop_on_success and history.last_success is True:
            return None

        if history.attempts >= len(self.actions):
            return None

        return self.actions[history.attempts]


def select_policy(
    policies: list[RecoveryPolicy],
    result: HealthResult,
) -> RecoveryPolicy | None:
    """Select the highest-priority policy matching a health result."""
    matching_policies = [policy for policy in policies if policy.applies_to(result)]

    if not matching_policies:
        return None

    return max(matching_policies, key=lambda policy: policy.priority)
