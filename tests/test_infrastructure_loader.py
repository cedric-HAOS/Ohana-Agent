from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from loader import InfrastructureLoader


def test_loader_returns_infrastructure_config() -> None:
    loader = InfrastructureLoader()

    config = loader.load(Path("config/infrastructure.example.yaml"))

    assert config.infrastructure.id == "ohana-house"


def test_loader_loads_nodes() -> None:
    loader = InfrastructureLoader()

    config = loader.load("config/infrastructure.example.yaml")

    assert len(config.nodes) == 6
    assert {node.id for node in config.nodes} == {
        "box-01",
        "infra-01",
        "zwave-01",
        "linky-01",
        "ha-01",
        "shelly-cuisine",
    }


def test_loader_loads_services() -> None:
    loader = InfrastructureLoader()

    config = loader.load("config/infrastructure.example.yaml")

    assert len(config.services) == 10

    assert config.services[0].id == "dhcp-primary"
    assert config.services[0].implementation == "dnsmasq"
    assert config.services[0].critical is True


def test_loader_loads_endpoints() -> None:
    loader = InfrastructureLoader()

    config = loader.load("config/infrastructure.example.yaml")

    assert config.services[0].port == 67


def test_loader_accepts_path_object() -> None:
    loader = InfrastructureLoader()

    config = loader.load(Path("config/infrastructure.example.yaml"))

    assert config.infrastructure.name == "Ohana House"


def test_infrastructure_loader_raises_for_missing_file(
    tmp_path: Path,
) -> None:
    """Preserve FileNotFoundError for a missing infrastructure file."""
    missing_path = tmp_path / "missing.yaml"

    with pytest.raises(FileNotFoundError):
        InfrastructureLoader().load(missing_path)


def test_infrastructure_loader_raises_for_invalid_yaml(
    tmp_path: Path,
) -> None:
    """Preserve the YAML parsing error for malformed infrastructure."""
    config_path = tmp_path / "infrastructure.yaml"
    config_path.write_text(
        "infrastructure: [\n",
        encoding="utf-8",
    )

    with pytest.raises(yaml.YAMLError):
        InfrastructureLoader().load(config_path)


def test_infrastructure_loader_rejects_empty_document(
    tmp_path: Path,
) -> None:
    """Reject an empty infrastructure document."""
    config_path = tmp_path / "infrastructure.yaml"
    config_path.write_text(
        "",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="infrastructure"):
        InfrastructureLoader().load(config_path)


def test_infrastructure_loader_rejects_non_mapping_yaml(
    tmp_path: Path,
) -> None:
    """Reject an infrastructure document that is not an object."""
    config_path = tmp_path / "infrastructure.yaml"
    config_path.write_text(
        "- infra-01\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        InfrastructureLoader().load(config_path)


def test_loader_loads_complete_topology() -> None:
    config = InfrastructureLoader().load("config/infrastructure.example.yaml")

    assert config.topology is not None
    assert len(config.topology.devices) == 11
    assert len(config.topology.links) == 10
    assert len(config.topology.layouts) == 1
    assert config.topology.layouts[0].positions["sw-01"].column == 2
