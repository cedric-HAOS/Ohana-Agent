"""Tests for recovery actions."""

from __future__ import annotations

from ohana_agent.recovery.action import NoopRecoveryAction


def test_noop_recovery_action_executes_successfully() -> None:
    action = NoopRecoveryAction(name="noop", source="plugin.dns")

    result = action.execute()

    assert result.success is True
    assert result.action == "noop"
    assert result.source == "plugin.dns"
    assert result.message == "No operation performed."


def test_noop_recovery_action_accepts_custom_message() -> None:
    action = NoopRecoveryAction(
        name="noop",
        source="mqtt.runtime",
        message="Nothing to recover.",
    )

    result = action.execute()

    assert result.message == "Nothing to recover."
