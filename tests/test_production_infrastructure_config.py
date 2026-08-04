from pathlib import Path

from loader import InfrastructureLoader


def test_production_infrastructure_declares_infrastructure_nodes() -> None:
    config = InfrastructureLoader().load(Path("config/infrastructure.yaml"))

    nodes = {node.id: node for node in config.nodes}

    assert set(nodes) == {"infra-01", "zwave-01"}
    assert nodes["infra-01"].endpoint.address == "192.168.1.10"
    assert nodes["zwave-01"].endpoint.address == "192.168.1.11"


def test_production_infrastructure_declares_primary_services() -> None:
    config = InfrastructureLoader().load(Path("config/infrastructure.yaml"))

    services = {service.id: service for service in config.services}

    assert set(services) == {
        "dhcp-primary",
        "dns-primary",
        "zwave-primary",
    }

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

    zwave = services["zwave-primary"]
    assert zwave.type == "zwave"
    assert zwave.node == "zwave-01"
    assert zwave.port == 3000
    assert zwave.critical is True

    assert config.topology is not None
    zwave_gateway = next(
        device for device in config.topology.devices if device.id == "rpi-zwave"
    )
    assert zwave_gateway.node == "zwave-01"
    assert zwave_gateway.metadata["role"] == "zwave_gateway"
