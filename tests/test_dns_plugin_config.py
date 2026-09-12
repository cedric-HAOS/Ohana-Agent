import pytest
from pydantic import ValidationError

from ohana_agent.configuration.dns import DNSPluginConfig, DNSPolicyConfig


def test_dns_plugin_config_has_defaults() -> None:
    config = DNSPluginConfig()

    assert config.services == []
    assert config.queries == []
    assert config.timeout == 2.0
    assert config.retries == 1
    assert config.policy == DNSPolicyConfig()


def test_dns_plugin_config_accepts_declarative_values() -> None:
    config = DNSPluginConfig(
        services=[
            "dns-primary",
            "dns-secondary",
        ],
        queries=[
            "example.com",
            "openai.com",
        ],
        timeout=1.5,
        retries=2,
        policy=DNSPolicyConfig(
            minimum_healthy_servers=2,
        ),
    )

    assert config.services == [
        "dns-primary",
        "dns-secondary",
    ]
    assert config.queries == [
        "example.com",
        "openai.com",
    ]
    assert config.timeout == 1.5
    assert config.retries == 2
    assert config.policy.minimum_healthy_servers == 2


def test_dns_plugin_config_strips_service_identifiers() -> None:
    config = DNSPluginConfig(
        services=[
            " dns-primary ",
        ],
    )

    assert config.services == ["dns-primary"]


def test_dns_plugin_config_rejects_empty_service_identifier() -> None:
    with pytest.raises(ValidationError):
        DNSPluginConfig(
            services=[""],
        )


def test_dns_plugin_config_rejects_empty_query() -> None:
    with pytest.raises(ValidationError):
        DNSPluginConfig(
            queries=["   "],
        )
