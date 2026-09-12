"""Tests for recovery results."""

from __future__ import annotations

from ohana_agent.recovery.result import RecoveryResult


def test_recovery_result_contains_required_fields() -> None:
    result = RecoveryResult(
        success=True,
        action="restart",
        source="plugin.dns",
    )

    assert result.success is True
    assert result.action == "restart"
    assert result.source == "plugin.dns"
    assert result.message is None
    assert result.details is None


def test_recovery_result_accepts_message_and_details() -> None:
    result = RecoveryResult(
        success=False,
        action="restart",
        source="plugin.dhcp",
        message="Restart failed.",
        details={"attempt": 1},
    )

    assert result.success is False
    assert result.message == "Restart failed."
    assert result.details == {"attempt": 1}
