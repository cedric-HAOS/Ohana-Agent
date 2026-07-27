"""Tests for the example configuration files."""

from configuration.loader import ConfigurationLoader
from loader.dns_config_loader import DNSConfigLoader
from loader.infrastructure_loader import InfrastructureLoader
from loader.ntp_config_loader import NTPConfigLoader


def test_shikamaru_example_configuration_is_valid() -> None:
    """Load the complete example application configuration."""
    configuration = ConfigurationLoader.load(
        "config/shikamaru.example.yaml",
    )

    assert configuration.version == 1
    assert configuration.agent.name == "Shikamaru"
    assert configuration.mqtt.host == "localhost"
    assert configuration.vision.enabled is True


def test_shikamaru_development_configuration_is_valid() -> None:
    configuration = ConfigurationLoader.load("config/shikamaru.development.yaml")

    assert configuration.administration.enabled is True
    assert configuration.administration.dhcp.enabled is True
    assert configuration.administration.dhcp.validation_command is None


def test_infrastructure_example_configuration_is_valid() -> None:
    """Load the example infrastructure configuration."""
    configuration = InfrastructureLoader().load(
        "config/infrastructure.example.yaml",
    )

    assert configuration.infrastructure.id == "ohana-house"
    assert configuration.nodes
    assert configuration.services


def test_dns_example_configuration_is_valid() -> None:
    """Load the example DNS plugin configuration."""
    configuration = DNSConfigLoader().load(
        "config/plugins/dns.example.yaml",
    )

    assert configuration.services == []
    assert configuration.queries == ["example.com"]
    assert configuration.policy.minimum_healthy_servers == 1


def test_ntp_example_configuration_is_valid() -> None:
    """Load the example NTP plugin configuration."""
    configuration = NTPConfigLoader().load(
        "config/plugins/ntp.example.yaml",
    )

    assert configuration.timeout == 2.0
    assert configuration.retries == 1
    assert configuration.interval_seconds == 60
    assert configuration.policy.maximum_offset_ms == 1000.0
    assert configuration.policy.maximum_stratum == 15
