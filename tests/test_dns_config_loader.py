from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from configuration.dns import DNSPluginConfig
from loader import DNSConfigLoader


def test_dns_config_loader_loads_dns_yaml() -> None:
    loader = DNSConfigLoader()

    config = loader.load("config/plugins/dns.yaml")

    assert isinstance(config, DNSPluginConfig)
    assert config.services == []
    assert config.queries == [
        "example.com",
    ]
    assert config.timeout == 2.0
    assert config.retries == 1
    assert config.policy.minimum_healthy_servers == 1
    assert config.interval_seconds == 60


def test_dns_config_loader_accepts_path_object() -> None:
    loader = DNSConfigLoader()

    config = loader.load(Path("config/plugins/dns.yaml"))

    assert config.services == []


def test_dns_config_loader_raises_for_missing_file(
    tmp_path: Path,
) -> None:
    """Preserve FileNotFoundError for a missing DNS configuration."""
    missing_path = tmp_path / "missing.yaml"

    with pytest.raises(FileNotFoundError):
        DNSConfigLoader().load(missing_path)


def test_dns_config_loader_raises_for_invalid_yaml(
    tmp_path: Path,
) -> None:
    """Preserve the YAML parsing error for malformed DNS configuration."""
    config_path = tmp_path / "dns.yaml"
    config_path.write_text(
        "services: [\n",
        encoding="utf-8",
    )

    with pytest.raises(yaml.YAMLError):
        DNSConfigLoader().load(config_path)


def test_dns_config_loader_rejects_non_mapping_yaml(
    tmp_path: Path,
) -> None:
    """Reject a DNS configuration that is not an object."""
    config_path = tmp_path / "dns.yaml"
    config_path.write_text(
        "- dns-primary\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        DNSConfigLoader().load(config_path)
