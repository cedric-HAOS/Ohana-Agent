from ohana_agent.plugins.dns.config import (
    DNSConfig,
    DNSPolicyConfig,
    DNSServerConfig,
)


def test_dns_server_config_defaults_to_enabled() -> None:
    server = DNSServerConfig(
        name="DNS-01",
        address="192.168.1.54",
    )

    assert server.name == "DNS-01"
    assert server.address == "192.168.1.54"
    assert server.enabled is True


def test_dns_policy_config_defaults_to_one_minimum_server() -> None:
    policy = DNSPolicyConfig()

    assert policy.minimum_healthy_servers == 1


def test_dns_config_defaults() -> None:
    config = DNSConfig()

    assert config.servers == []
    assert config.queries == []
    assert config.timeout == 2.0
    assert config.retries == 1
    assert config.policy == DNSPolicyConfig()


def test_dns_config_accepts_servers_queries_and_policy() -> None:
    config = DNSConfig(
        servers=[
            DNSServerConfig(
                name="DNS-01",
                address="192.168.1.54",
            ),
            DNSServerConfig(
                name="DNS-02",
                address="192.168.1.55",
                enabled=False,
            ),
        ],
        queries=["openai.com", "github.com"],
        timeout=1.5,
        retries=2,
        policy=DNSPolicyConfig(minimum_healthy_servers=1),
    )

    assert len(config.servers) == 2
    assert config.servers[0].name == "DNS-01"
    assert config.servers[0].address == "192.168.1.54"
    assert config.servers[0].enabled is True
    assert config.servers[1].name == "DNS-02"
    assert config.servers[1].address == "192.168.1.55"
    assert config.servers[1].enabled is False
    assert config.queries == ["openai.com", "github.com"]
    assert config.timeout == 1.5
    assert config.retries == 2
    assert config.policy.minimum_healthy_servers == 1
