from ohana_agent.observation import ObserverResult, ObserverStatistics


def test_observer_statistics_defaults() -> None:
    statistics = ObserverStatistics()

    assert statistics.observations == 0
    assert statistics.successes == 0
    assert statistics.failures == 0
    assert statistics.total_latency == 0.0
    assert statistics.min_latency is None
    assert statistics.max_latency is None


def test_observer_statistics_records_success() -> None:
    statistics = ObserverStatistics()

    statistics.record(ObserverResult(success=True, latency=12.0))

    assert statistics.observations == 1
    assert statistics.successes == 1
    assert statistics.failures == 0


def test_observer_statistics_records_failure() -> None:
    statistics = ObserverStatistics()

    statistics.record(ObserverResult(success=False, latency=12.0))

    assert statistics.observations == 1
    assert statistics.successes == 0
    assert statistics.failures == 1


def test_observer_statistics_records_multiple_results() -> None:
    statistics = ObserverStatistics()

    statistics.record(ObserverResult(success=True, latency=10.0))
    statistics.record(ObserverResult(success=False, latency=20.0))
    statistics.record(ObserverResult(success=True, latency=30.0))

    assert statistics.observations == 3
    assert statistics.successes == 2
    assert statistics.failures == 1


def test_observer_statistics_computes_success_rate() -> None:
    statistics = ObserverStatistics()

    statistics.record(ObserverResult(success=True, latency=10.0))
    statistics.record(ObserverResult(success=False, latency=20.0))
    statistics.record(ObserverResult(success=True, latency=30.0))

    assert statistics.success_rate == 66.66666666666666


def test_observer_statistics_success_rate_defaults_to_zero() -> None:
    statistics = ObserverStatistics()

    assert statistics.success_rate == 0.0


def test_observer_statistics_computes_failure_rate() -> None:
    statistics = ObserverStatistics()

    statistics.record(ObserverResult(success=True, latency=10.0))
    statistics.record(ObserverResult(success=False, latency=20.0))
    statistics.record(ObserverResult(success=True, latency=30.0))

    assert statistics.failure_rate == 33.33333333333333


def test_observer_statistics_failure_rate_defaults_to_zero() -> None:
    statistics = ObserverStatistics()

    assert statistics.failure_rate == 0.0


def test_observer_statistics_computes_average_latency() -> None:
    statistics = ObserverStatistics()

    statistics.record(ObserverResult(success=True, latency=10.0))
    statistics.record(ObserverResult(success=False, latency=20.0))
    statistics.record(ObserverResult(success=True, latency=30.0))

    assert statistics.average_latency == 20.0


def test_observer_statistics_average_latency_defaults_to_zero() -> None:
    statistics = ObserverStatistics()

    assert statistics.average_latency == 0.0


def test_observer_statistics_tracks_min_latency() -> None:
    statistics = ObserverStatistics()

    statistics.record(ObserverResult(success=True, latency=30.0))
    statistics.record(ObserverResult(success=True, latency=10.0))
    statistics.record(ObserverResult(success=True, latency=20.0))

    assert statistics.min_latency == 10.0


def test_observer_statistics_tracks_max_latency() -> None:
    statistics = ObserverStatistics()

    statistics.record(ObserverResult(success=True, latency=30.0))
    statistics.record(ObserverResult(success=True, latency=10.0))
    statistics.record(ObserverResult(success=True, latency=20.0))

    assert statistics.max_latency == 30.0
