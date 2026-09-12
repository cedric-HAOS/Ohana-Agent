from datetime import UTC, datetime

from ohana_agent.core import Runtime


def test_runtime_defaults() -> None:
    runtime = Runtime()

    assert runtime.started_at is None
    assert runtime.stopped_at is None


def test_runtime_accepts_dates() -> None:
    started_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    stopped_at = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)

    runtime = Runtime(started_at=started_at, stopped_at=stopped_at)

    assert runtime.started_at == started_at
    assert runtime.stopped_at == stopped_at
