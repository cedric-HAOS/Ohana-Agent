from pathlib import Path

from loader import InfrastructureLoader


def test_production_infrastructure_declares_infra_01() -> None:
    config = InfrastructureLoader().load(Path("config/infrastructure.yaml"))

    assert len(config.nodes) == 1

    node = config.nodes[0]

    assert node.id == "infra-01"
    assert node.endpoint.address == "192.168.1.10"


def test_production_infrastructure_declares_primary_dhcp_and_dns() -> None:
    config = InfrastructureLoader().load(Path("config/infrastructure.yaml"))

    services = {service.id: service for service in config.services}

    assert set(services) == {"dhcp-primary", "dns-primary"}

    dhcp = services["dhcp-primary"]
    assert dhcp.type == "dhcp"
    assert dhcp.node == "infra-01"
    assert dhcp.port == 67
    assert dhcp.implementation == "dnsmasq"
    assert dhcp.critical is True

    dns = services["dns-primary"]
    assert dns.type == "dns"
    assert dns.node == "infra-01"
    assert dns.port == 53
