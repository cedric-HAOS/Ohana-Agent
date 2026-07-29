"""Tests for the example configuration files."""

from configuration.loader import ConfigurationLoader
from loader.dhcp_config_loader import DHCPConfigLoader
from loader.dns_config_loader import DNSConfigLoader
from loader.infrastructure_loader import InfrastructureLoader
from loader.mqtt_config_loader import MQTTConfigLoader
from loader.network_config_loader import NetworkConfigLoader
from loader.ntp_config_loader import NTPConfigLoader
from loader.shelly_telemetry_config_loader import ShellyTelemetryConfigLoader
from loader.teleinformation_config_loader import TeleinformationConfigLoader
from loader.wireguard_config_loader import WireGuardConfigLoader
from loader.zwave_config_loader import ZWaveConfigLoader


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


def test_dhcp_example_configuration_is_valid() -> None:
    """Load the example DHCP observation plugin configuration."""
    configuration = DHCPConfigLoader().load(
        "config/plugins/dhcp.example.yaml",
    )

    assert configuration.enabled is True
    assert configuration.timeout == 3.0
    assert configuration.interval_seconds == 60
    assert configuration.policy.maximum_pool_usage_percent == 90.0
    assert configuration.check_service_active is True


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


def test_mqtt_example_configuration_is_valid() -> None:
    """Load the example MQTT observation plugin configuration."""
    configuration = MQTTConfigLoader().load(
        "config/plugins/mqtt.example.yaml",
    )

    assert configuration.timeout == 5.0
    assert configuration.retries == 1
    assert configuration.interval_seconds == 60
    assert configuration.qos == 1
    assert configuration.authentication.username is None
    assert configuration.tls.enabled is False


def test_network_example_configuration_is_valid() -> None:
    """Load the example network presence plugin configuration."""
    configuration = NetworkConfigLoader().load(
        "config/plugins/network.example.yaml",
    )

    assert configuration.enabled is True
    assert configuration.timeout == 1.0
    assert configuration.retries == 0
    assert configuration.interval_seconds == 60
    assert configuration.failure_threshold == 3


def test_zwave_example_configuration_is_valid() -> None:
    configuration = ZWaveConfigLoader().load(
        "config/plugins/zwave.example.yaml",
    )

    assert configuration.enabled is True
    assert configuration.timeout == 3.0
    assert configuration.verify_tls is True


def test_wireguard_example_configuration_is_valid() -> None:
    configuration = WireGuardConfigLoader().load(
        "config/plugins/wireguard.example.yaml",
    )

    assert configuration.enabled is True
    assert configuration.timeout == 3.0
    assert configuration.app_id == "fr.ohana.agent"
    assert configuration.app_token is None


def test_shelly_telemetry_example_configuration_is_valid() -> None:
    configuration = ShellyTelemetryConfigLoader().load(
        "config/plugins/shelly-telemetry.example.yaml",
    )

    assert configuration.enabled is True
    assert configuration.maximum_age_seconds == 900
    assert configuration.home_assistant_url == ("http://ha-green.ohana.lan:8123")
    assert configuration.devices == []


def test_teleinformation_example_configuration_is_valid() -> None:
    configuration = TeleinformationConfigLoader().load(
        "config/plugins/teleinformation.example.yaml",
    )

    assert configuration.enabled is True
    assert configuration.interval_seconds == 60
    assert configuration.maximum_age_seconds == 180
    assert configuration.home_assistant_url == ("http://ha-green.ohana.lan:8123")
    assert configuration.access_token_environment_variable == (
        "OHANA_HOME_ASSISTANT_TOKEN"
    )
