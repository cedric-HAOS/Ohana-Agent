from ohana_agent.plugins.dns.capability_runtime import DNSCapabilityRuntime


def test_dns_capability_runtime_initial_state() -> None:
    runtime = DNSCapabilityRuntime()

    assert runtime.total_servers == 0
    assert runtime.healthy_servers == 0
    assert runtime.failed_servers == 0
    assert runtime.healthy is None


def test_dns_capability_runtime_is_healthy_when_policy_is_met() -> None:
    runtime = DNSCapabilityRuntime()

    runtime.update(
        total_servers=2,
        healthy_servers=1,
        minimum_healthy_servers=1,
    )

    assert runtime.total_servers == 2
    assert runtime.healthy_servers == 1
    assert runtime.failed_servers == 1
    assert runtime.healthy is True


def test_dns_capability_runtime_is_failed_when_policy_is_not_met() -> None:
    runtime = DNSCapabilityRuntime()

    runtime.update(
        total_servers=2,
        healthy_servers=0,
        minimum_healthy_servers=1,
    )

    assert runtime.total_servers == 2
    assert runtime.healthy_servers == 0
    assert runtime.failed_servers == 2
    assert runtime.healthy is False


def test_dns_capability_runtime_supports_strict_policy() -> None:
    runtime = DNSCapabilityRuntime()

    runtime.update(
        total_servers=2,
        healthy_servers=1,
        minimum_healthy_servers=2,
    )

    assert runtime.total_servers == 2
    assert runtime.healthy_servers == 1
    assert runtime.failed_servers == 1
    assert runtime.healthy is False
