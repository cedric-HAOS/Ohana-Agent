# tests/test_dns_runtime.py

from ohana_agent.plugins.dns.runtime import DNSRuntime


def test_dns_runtime_initial_state() -> None:
    runtime = DNSRuntime()

    assert runtime.total_checks == 0
    assert runtime.successful_checks == 0
    assert runtime.failed_checks == 0
    assert runtime.last_hostname is None
    assert runtime.last_address is None
    assert runtime.last_error is None
    assert runtime.healthy is None


def test_dns_runtime_records_success() -> None:
    runtime = DNSRuntime()

    runtime.record_success(
        hostname="example.com",
        address="93.184.216.34",
    )

    assert runtime.total_checks == 1
    assert runtime.successful_checks == 1
    assert runtime.failed_checks == 0
    assert runtime.last_hostname == "example.com"
    assert runtime.last_address == "93.184.216.34"
    assert runtime.last_error is None
    assert runtime.healthy is True


def test_dns_runtime_records_failure() -> None:
    runtime = DNSRuntime()

    runtime.record_failure(
        hostname="missing.local",
        error="host not found",
    )

    assert runtime.total_checks == 1
    assert runtime.successful_checks == 0
    assert runtime.failed_checks == 1
    assert runtime.last_hostname == "missing.local"
    assert runtime.last_address is None
    assert runtime.last_error == "host not found"
    assert runtime.healthy is False
