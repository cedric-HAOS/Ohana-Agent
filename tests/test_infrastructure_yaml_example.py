# tests/test_infrastructure_yaml_example.py

from pathlib import Path

import yaml


def test_infrastructure_example_yaml_exists() -> None:
    path = Path("config/infrastructure.example.yaml")

    assert path.exists()


def test_infrastructure_example_yaml_has_expected_root_sections() -> None:
    path = Path("config/infrastructure.example.yaml")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert "infrastructure" in data
    assert "metadata" in data
    assert "nodes" in data
    assert "services" in data
    assert "topology" in data


def test_infrastructure_example_yaml_declares_infrastructure_identity() -> None:
    path = Path("config/infrastructure.example.yaml")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert data["infrastructure"]["id"] == "ohana-house"
    assert data["infrastructure"]["name"] == "Ohana House"
    assert data["infrastructure"]["environment"] == "production"


def test_infrastructure_example_yaml_declares_nodes() -> None:
    path = Path("config/infrastructure.example.yaml")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    nodes = data["nodes"]

    assert len(nodes) == 6
    nodes_by_id = {node["id"]: node for node in nodes}
    assert nodes_by_id["infra-01"]["endpoint"]["type"] == "ip"
    assert nodes_by_id["infra-01"]["endpoint"]["address"] == "192.168.1.10"
    assert nodes_by_id["box-01"]["endpoint"]["address"] == "192.168.1.1"


def test_infrastructure_example_yaml_declares_services() -> None:
    path = Path("config/infrastructure.example.yaml")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    services = data["services"]

    assert len(services) == 10
    services_by_id = {service["id"]: service for service in services}
    assert services_by_id["dhcp-primary"]["type"] == "dhcp"
    assert services_by_id["dhcp-primary"]["node"] == "infra-01"
    assert services_by_id["wireguard-freebox"]["type"] == "wireguard"
    assert services_by_id["wireguard-freebox"]["node"] == "box-01"
    assert services_by_id["shelly-telemetry-cuisine"]["type"] == "shelly_telemetry"
    teleinformation = services_by_id["teleinformation"]
    assert teleinformation["type"] == "teleinformation"
    assert teleinformation["node"] == "linky-01"
    assert teleinformation["implementation"] == (
        "teleinfo2mqtt via MQTT et Home Assistant"
    )
    assert teleinformation["metadata"]["apparent_power_entity_id"] == (
        "sensor.teleinfo_041964385922_sinsts"
    )
    assert teleinformation["metadata"]["tariff_entity_id"] == (
        "sensor.teleinfo_041964385922_ntarf"
    )
    assert teleinformation["metadata"]["red_peak_entity_id"] == (
        "sensor.teleinfo_041964385922_easf06"
    )


def test_infrastructure_example_yaml_declares_service_endpoints() -> None:
    path = Path("config/infrastructure.example.yaml")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    dhcp_service = data["services"][0]

    assert dhcp_service["port"] == 67
    assert dhcp_service["implementation"] == "dnsmasq"
    assert dhcp_service["critical"] is True


def test_infrastructure_example_yaml_declares_topology() -> None:
    path = Path("config/infrastructure.example.yaml")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    topology = data["topology"]

    assert topology["devices"]
    assert topology["links"]
    assert topology["layouts"]
