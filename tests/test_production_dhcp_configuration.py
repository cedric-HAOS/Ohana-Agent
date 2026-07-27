from pathlib import Path

from builder.dhcp_configuration_builder import DHCPConfigurationBuilder
from loader import DHCPConfigLoader, InfrastructureLoader


def test_production_dhcp_configuration_is_enabled() -> None:
    plugin_config = DHCPConfigLoader().load(Path("config/plugins/dhcp.yaml"))
    infrastructure = InfrastructureLoader().load(Path("config/infrastructure.yaml"))

    from builder import InfrastructureBuilder

    runtime = DHCPConfigurationBuilder().build(
        InfrastructureBuilder().build(infrastructure),
        plugin_config,
        server_node_id="infra-01",
        main_config_path=Path("/etc/dnsmasq.d/00-ohana.conf"),
        leases_path=Path("/var/lib/misc/dnsmasq.leases"),
    )

    assert plugin_config.enabled is True
    assert plugin_config.check_service_active is True
    assert plugin_config.interval_seconds == 60
    assert plugin_config.policy.maximum_pool_usage_percent == 90.0
    assert len(runtime.servers) == 1
    assert runtime.servers[0].name == "dhcp-primary"
    assert runtime.servers[0].address == "192.168.1.10"
    assert runtime.servers[0].port == 67
    assert runtime.service_status_command == (
        "/usr/bin/systemctl",
        "is-active",
        "dnsmasq.service",
    )
