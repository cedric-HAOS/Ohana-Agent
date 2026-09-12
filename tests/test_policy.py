"""Tests for recovery policies."""

from __future__ import annotations

from ohana_agent.observation.health.monitor import HealthResult, HealthStatus
from ohana_agent.recovery.action import NoopRecoveryAction
from ohana_agent.recovery.policy import (
    RecoveryHistory,
    SequentialRecoveryPolicy,
    select_policy,
)
from ohana_agent.recovery.result import RecoveryResult


def test_recovery_history_records_result() -> None:
    history = RecoveryHistory(source="plugin.dns")
    result = RecoveryResult(
        success=True,
        action="restart",
        source="plugin.dns",
    )

    updated = history.record(result)

    assert updated.source == "plugin.dns"
    assert updated.attempts == 1
    assert updated.last_action == "restart"
    assert updated.last_success is True
    assert updated.results == (result,)


def test_recovery_history_is_immutable() -> None:
    history = RecoveryHistory(source="plugin.dns")
    result = RecoveryResult(
        success=True,
        action="restart",
        source="plugin.dns",
    )

    updated = history.record(result)

    assert history.attempts == 0
    assert history.results == ()
    assert updated.attempts == 1


def test_sequential_policy_applies_to_configured_source_and_status() -> None:
    policy = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[NoopRecoveryAction(name="restart", source="plugin.dns")],
    )

    assert policy.applies_to(
        HealthResult(name="plugin.dns", status=HealthStatus.DEGRADED),
    )
    assert policy.applies_to(
        HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY),
    )


def test_sequential_policy_rejects_other_source() -> None:
    policy = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[NoopRecoveryAction(name="restart", source="plugin.dns")],
    )

    assert not policy.applies_to(
        HealthResult(name="plugin.dhcp", status=HealthStatus.UNHEALTHY),
    )


def test_sequential_policy_rejects_unconfigured_status() -> None:
    policy = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[NoopRecoveryAction(name="restart", source="plugin.dns")],
        statuses={HealthStatus.UNHEALTHY},
    )

    assert policy.applies_to(
        HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY),
    )
    assert not policy.applies_to(
        HealthResult(name="plugin.dns", status=HealthStatus.DEGRADED),
    )


def test_sequential_policy_returns_first_action_without_history() -> None:
    restart = NoopRecoveryAction(name="restart", source="plugin.dns")
    reload_action = NoopRecoveryAction(name="reload", source="plugin.dns")
    policy = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[restart, reload_action],
    )

    action = policy.next_action(RecoveryHistory(source="plugin.dns"))

    assert action == restart


def test_sequential_policy_returns_next_action_after_failure() -> None:
    restart = NoopRecoveryAction(name="restart", source="plugin.dns")
    reload_action = NoopRecoveryAction(name="reload", source="plugin.dns")
    policy = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[restart, reload_action],
    )

    history = RecoveryHistory(source="plugin.dns").record(
        RecoveryResult(
            success=False,
            action="restart",
            source="plugin.dns",
        ),
    )

    action = policy.next_action(history)

    assert action == reload_action


def test_sequential_policy_stops_after_success_by_default() -> None:
    restart = NoopRecoveryAction(name="restart", source="plugin.dns")
    reload_action = NoopRecoveryAction(name="reload", source="plugin.dns")
    policy = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[restart, reload_action],
    )

    history = RecoveryHistory(source="plugin.dns").record(
        RecoveryResult(
            success=True,
            action="restart",
            source="plugin.dns",
        ),
    )

    assert policy.next_action(history) is None


def test_sequential_policy_can_continue_after_success_when_configured() -> None:
    restart = NoopRecoveryAction(name="restart", source="plugin.dns")
    reload_action = NoopRecoveryAction(name="reload", source="plugin.dns")
    policy = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[restart, reload_action],
        stop_on_success=False,
    )

    history = RecoveryHistory(source="plugin.dns").record(
        RecoveryResult(
            success=True,
            action="restart",
            source="plugin.dns",
        ),
    )

    assert policy.next_action(history) == reload_action


def test_sequential_policy_returns_none_when_actions_are_exhausted() -> None:
    restart = NoopRecoveryAction(name="restart", source="plugin.dns")
    policy = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[restart],
    )

    history = RecoveryHistory(source="plugin.dns").record(
        RecoveryResult(
            success=False,
            action="restart",
            source="plugin.dns",
        ),
    )

    assert policy.next_action(history) is None


def test_sequential_policy_returns_none_for_other_history_source() -> None:
    restart = NoopRecoveryAction(name="restart", source="plugin.dns")
    policy = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[restart],
    )

    history = RecoveryHistory(source="plugin.dhcp")

    assert policy.next_action(history) is None


def test_select_policy_returns_none_without_match() -> None:
    policy = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[NoopRecoveryAction(name="restart", source="plugin.dns")],
    )

    selected = select_policy(
        [policy],
        HealthResult(name="plugin.dhcp", status=HealthStatus.UNHEALTHY),
    )

    assert selected is None


def test_select_policy_returns_matching_policy() -> None:
    policy = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[NoopRecoveryAction(name="restart", source="plugin.dns")],
    )

    selected = select_policy(
        [policy],
        HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY),
    )

    assert selected == policy


def test_select_policy_returns_highest_priority_policy() -> None:
    low_priority = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[NoopRecoveryAction(name="restart", source="plugin.dns")],
        priority=10,
    )
    high_priority = SequentialRecoveryPolicy(
        source="plugin.dns",
        actions=[NoopRecoveryAction(name="disable", source="plugin.dns")],
        priority=100,
    )

    selected = select_policy(
        [low_priority, high_priority],
        HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY),
    )

    assert selected == high_priority
