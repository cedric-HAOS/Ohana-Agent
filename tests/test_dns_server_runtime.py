from ohana_agent.plugins.dns.server_runtime import DNSServerRuntime


def test_dns_server_runtime_initial_state() -> None:
    runtime = DNSServerRuntime()

    assert runtime.total_checks == 0
    assert runtime.successful_checks == 0
    assert runtime.failed_checks == 0
    assert runtime.last_hostname is None
    assert runtime.last_address is None
    assert runtime.last_error is None
    assert runtime.healthy is None


def test_dns_server_runtime_records_success() -> None:
    runtime = DNSServerRuntime()

    runtime.record_success(
        hostname="openai.com",
        address="104.18.32.47",
    )

    assert runtime.total_checks == 1
    assert runtime.successful_checks == 1
    assert runtime.failed_checks == 0
    assert runtime.last_hostname == "openai.com"
    assert runtime.last_address == "104.18.32.47"
    assert runtime.last_error is None
    assert runtime.healthy is True


def test_dns_server_runtime_records_failure() -> None:
    runtime = DNSServerRuntime()

    runtime.record_failure(
        hostname="openai.com",
        error="timeout",
    )

    assert runtime.total_checks == 1
    assert runtime.successful_checks == 0
    assert runtime.failed_checks == 1
    assert runtime.last_hostname == "openai.com"
    assert runtime.last_address is None
    assert runtime.last_error == "timeout"
    assert runtime.healthy is False
