from __future__ import annotations

import pytest

from ohana_agent.core.mqtt.reconnect import MQTTReconnectPolicy


def test_default_policy_is_enabled() -> None:
    policy = MQTTReconnectPolicy()

    assert policy.enabled is True
    assert policy.should_retry() is True


def test_default_policy_uses_expected_values() -> None:
    policy = MQTTReconnectPolicy()

    assert policy.initial_delay_seconds == 1
    assert policy.max_delay_seconds == 30


def test_get_delay_returns_initial_delay_for_first_attempt() -> None:
    policy = MQTTReconnectPolicy(
        initial_delay_seconds=1,
        max_delay_seconds=30,
    )

    assert policy.get_delay(0) == 1


def test_get_delay_uses_exponential_backoff() -> None:
    policy = MQTTReconnectPolicy(
        initial_delay_seconds=1,
        max_delay_seconds=30,
    )

    assert policy.get_delay(0) == 1
    assert policy.get_delay(1) == 2
    assert policy.get_delay(2) == 4
    assert policy.get_delay(3) == 8
    assert policy.get_delay(4) == 16


def test_get_delay_never_exceeds_max_delay() -> None:
    policy = MQTTReconnectPolicy(
        initial_delay_seconds=1,
        max_delay_seconds=30,
    )

    assert policy.get_delay(5) == 30
    assert policy.get_delay(6) == 30
    assert policy.get_delay(10) == 30


def test_get_delay_works_with_custom_initial_delay() -> None:
    policy = MQTTReconnectPolicy(
        initial_delay_seconds=3,
        max_delay_seconds=20,
    )

    assert policy.get_delay(0) == 3
    assert policy.get_delay(1) == 6
    assert policy.get_delay(2) == 12
    assert policy.get_delay(3) == 20


def test_disabled_policy_returns_zero_delay() -> None:
    policy = MQTTReconnectPolicy(
        enabled=False,
        initial_delay_seconds=1,
        max_delay_seconds=30,
    )

    assert policy.should_retry() is False
    assert policy.get_delay(0) == 0
    assert policy.get_delay(5) == 0


def test_delays_returns_delay_sequence() -> None:
    policy = MQTTReconnectPolicy(
        initial_delay_seconds=1,
        max_delay_seconds=30,
    )

    assert policy.delays(7) == [1, 2, 4, 8, 16, 30, 30]


def test_delays_returns_empty_list_for_zero_attempts() -> None:
    policy = MQTTReconnectPolicy()

    assert policy.delays(0) == []


def test_negative_attempt_raises_error() -> None:
    policy = MQTTReconnectPolicy()

    with pytest.raises(
        ValueError,
        match="attempt must be greater than or equal to 0",
    ):
        policy.get_delay(-1)


def test_negative_attempts_count_raises_error() -> None:
    policy = MQTTReconnectPolicy()

    with pytest.raises(
        ValueError,
        match="attempts must be greater than or equal to 0",
    ):
        policy.delays(-1)


def test_initial_delay_must_be_greater_than_zero() -> None:
    with pytest.raises(
        ValueError,
        match="initial_delay_seconds must be greater than 0",
    ):
        MQTTReconnectPolicy(initial_delay_seconds=0)


def test_max_delay_must_be_greater_than_zero() -> None:
    with pytest.raises(
        ValueError,
        match="max_delay_seconds must be greater than 0",
    ):
        MQTTReconnectPolicy(max_delay_seconds=0)


def test_initial_delay_must_not_exceed_max_delay() -> None:
    with pytest.raises(
        ValueError,
        match="initial_delay_seconds must be less than or equal to",
    ):
        MQTTReconnectPolicy(
            initial_delay_seconds=31,
            max_delay_seconds=30,
        )
