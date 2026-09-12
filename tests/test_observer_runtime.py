from ohana_agent.observation import ObserverResult, ObserverRuntime, ObserverState


def test_observer_runtime_initial_state_is_idle() -> None:
    runtime = ObserverRuntime()

    assert runtime.state == ObserverState.IDLE


def test_observer_runtime_initial_statistics_are_empty() -> None:
    runtime = ObserverRuntime()

    assert runtime.statistics.observations == 0
    assert runtime.statistics.successes == 0
    assert runtime.statistics.failures == 0


def test_observer_runtime_initial_last_result_is_none() -> None:
    runtime = ObserverRuntime()

    assert runtime.last_result is None


def test_observer_runtime_start_sets_running_state() -> None:
    runtime = ObserverRuntime()

    runtime.start()

    assert runtime.state == ObserverState.RUNNING


def test_observer_runtime_stop_sets_stopped_state() -> None:
    runtime = ObserverRuntime()

    runtime.stop()

    assert runtime.state == ObserverState.STOPPED


def test_observer_runtime_record_sets_last_result() -> None:
    runtime = ObserverRuntime()
    result = ObserverResult(success=True, latency=12.0)

    runtime.record(result)

    assert runtime.last_result is result


def test_observer_runtime_record_updates_statistics() -> None:
    runtime = ObserverRuntime()
    result = ObserverResult(success=True, latency=12.0)

    runtime.record(result)

    assert runtime.statistics.observations == 1
    assert runtime.statistics.successes == 1
    assert runtime.statistics.failures == 0


def test_observer_runtime_record_failure_updates_statistics() -> None:
    runtime = ObserverRuntime()
    result = ObserverResult(success=False, latency=42.0)

    runtime.record(result)

    assert runtime.statistics.observations == 1
    assert runtime.statistics.successes == 0
    assert runtime.statistics.failures == 1


def test_observer_runtime_record_multiple_results() -> None:
    runtime = ObserverRuntime()

    runtime.record(ObserverResult(success=True, latency=10.0))
    runtime.record(ObserverResult(success=False, latency=20.0))
    runtime.record(ObserverResult(success=True, latency=30.0))

    assert runtime.statistics.observations == 3
    assert runtime.statistics.successes == 2
    assert runtime.statistics.failures == 1
    assert runtime.statistics.average_latency == 20.0


def test_observer_runtime_last_result_is_latest_result() -> None:
    runtime = ObserverRuntime()
    first = ObserverResult(success=True, latency=10.0)
    second = ObserverResult(success=False, latency=20.0)

    runtime.record(first)
    runtime.record(second)

    assert runtime.last_result is second
