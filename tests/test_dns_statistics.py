# tests/test_dns_statistics.py

from ohana_agent.plugins.dns.runtime import DNSRuntime
from ohana_agent.plugins.dns.statistics import DNSStatistics


def test_dns_statistics_from_empty_runtime() -> None:
    runtime = DNSRuntime()

    statistics = DNSStatistics.from_runtime(runtime)

    assert statistics.total_checks == 0
    assert statistics.successful_checks == 0
    assert statistics.failed_checks == 0
    assert statistics.success_rate == 0.0
    assert statistics.healthy is None


def test_dns_statistics_from_successful_runtime() -> None:
    runtime = DNSRuntime()
    runtime.record_success(
        hostname="example.com",
        address="93.184.216.34",
    )

    statistics = DNSStatistics.from_runtime(runtime)

    assert statistics.total_checks == 1
    assert statistics.successful_checks == 1
    assert statistics.failed_checks == 0
    assert statistics.success_rate == 1.0
    assert statistics.healthy is True


def test_dns_statistics_from_failed_runtime() -> None:
    runtime = DNSRuntime()
    runtime.record_failure(
        hostname="missing.local",
        error="host not found",
    )

    statistics = DNSStatistics.from_runtime(runtime)

    assert statistics.total_checks == 1
    assert statistics.successful_checks == 0
    assert statistics.failed_checks == 1
    assert statistics.success_rate == 0.0
    assert statistics.healthy is False


def test_dns_statistics_from_mixed_runtime() -> None:
    runtime = DNSRuntime()
    runtime.record_success(
        hostname="example.com",
        address="93.184.216.34",
    )
    runtime.record_failure(
        hostname="missing.local",
        error="host not found",
    )

    statistics = DNSStatistics.from_runtime(runtime)

    assert statistics.total_checks == 2
    assert statistics.successful_checks == 1
    assert statistics.failed_checks == 1
    assert statistics.success_rate == 0.5
    assert statistics.healthy is False
