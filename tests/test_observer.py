import pytest

from ohana_agent.observation import Observer, ObserverResult, ObserverRuntime
from ohana_agent.observation.checks import FakeCheck


def test_observer_creates_default_runtime() -> None:
    observer = Observer()

    assert isinstance(observer.runtime, ObserverRuntime)


def test_observer_uses_injected_runtime() -> None:
    runtime = ObserverRuntime()

    observer = Observer(runtime=runtime)

    assert observer.runtime is runtime


def test_observer_observe_returns_check_result() -> None:
    expected = ObserverResult(success=True, latency=12.0)
    observer = Observer()
    check = FakeCheck(result=expected)

    result = observer.observe(check)

    assert result is expected


def test_observer_observe_records_result() -> None:
    expected = ObserverResult(success=True, latency=12.0)
    observer = Observer()
    check = FakeCheck(result=expected)

    observer.observe(check)

    assert observer.runtime.last_result is expected


def test_observer_observe_updates_statistics() -> None:
    observer = Observer()

    observer.observe(FakeCheck(result=ObserverResult(success=True, latency=10.0)))
    observer.observe(FakeCheck(result=ObserverResult(success=False, latency=20.0)))
    observer.observe(FakeCheck(result=ObserverResult(success=True, latency=30.0)))

    assert observer.runtime.statistics.observations == 3
    assert observer.runtime.statistics.successes == 2
    assert observer.runtime.statistics.failures == 1
    assert observer.runtime.statistics.average_latency == 20.0


def test_observer_observe_records_failure_result() -> None:
    observer = Observer()
    check = FakeCheck(
        result=ObserverResult(
            success=False,
            latency=42.0,
            message="fake failure",
        )
    )

    result = observer.observe(check)

    assert result.failed is True
    assert observer.runtime.statistics.failures == 1


def test_observer_observe_propagates_check_exception() -> None:
    class BrokenCheck(FakeCheck):
        def execute(self) -> ObserverResult:
            raise RuntimeError("check exploded")

    observer = Observer()

    with pytest.raises(RuntimeError, match="check exploded"):
        observer.observe(BrokenCheck())


def test_observer_does_not_record_when_check_raises() -> None:
    class BrokenCheck(FakeCheck):
        def execute(self) -> ObserverResult:
            raise RuntimeError("check exploded")

    observer = Observer()

    with pytest.raises(RuntimeError):
        observer.observe(BrokenCheck())

    assert observer.runtime.statistics.observations == 0
    assert observer.runtime.last_result is None
