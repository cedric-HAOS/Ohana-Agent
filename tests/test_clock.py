from datetime import UTC, datetime, timedelta

from ohana_agent.scheduler import FakeClock, SystemClock


def test_system_clock_returns_datetime() -> None:
    clock = SystemClock()

    assert isinstance(clock.now(), datetime)


def test_fake_clock_returns_configured_time() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock = FakeClock(now)

    assert clock.now() == now


def test_fake_clock_can_advance_time() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock = FakeClock(now)

    clock.advance(timedelta(seconds=30))

    assert clock.now() == now + timedelta(seconds=30)
