from pathlib import Path

from builder import (
    DNSConfigurationBuilder,
    InfrastructureBuilder,
)
from loader import DNSConfigLoader, InfrastructureLoader


def test_production_dns_service_resolves_to_infra_01() -> None:
    infrastructure_config = InfrastructureLoader().load(
        Path("config/infrastructure.yaml")
    )
    infrastructure = InfrastructureBuilder().build(infrastructure_config)
    plugin_config = DNSConfigLoader().load(Path("config/plugins/dns.yaml"))

    dns_config = DNSConfigurationBuilder().build(
        infrastructure,
        plugin_config,
    )

    assert len(dns_config.servers) == 1

    server = dns_config.servers[0]

    assert server.name == "dns-primary"
    assert server.address == "192.168.1.10"
    assert server.enabled is True


def test_production_dns_configuration_has_one_query() -> None:
    plugin_config = DNSConfigLoader().load(Path("config/plugins/dns.yaml"))

    assert plugin_config.services == []
    assert plugin_config.queries == ["example.com"]
    assert plugin_config.timeout == 2.0
    assert plugin_config.retries == 1
    assert plugin_config.interval_seconds == 60
