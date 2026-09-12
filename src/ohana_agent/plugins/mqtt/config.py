"""Runtime configuration used by the MQTT plugin."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MQTTBrokerConfig:
    """Configuration for one MQTT broker."""

    name: str
    address: str
    port: int = 1883
    enabled: bool = True
    node_id: str | None = None


@dataclass(frozen=True)
class MQTTAuthenticationConfig:
    """Credentials used by MQTT observations."""

    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class MQTTTLSConfig:
    """TLS settings used by MQTT observations."""

    enabled: bool = False
    ca_file: str | None = None
    insecure: bool = False


@dataclass(frozen=True)
class MQTTHomeAssistantConfig:
    """Home Assistant MQTT Discovery export settings."""

    enabled: bool = True
    discovery_enabled: bool = True
    discovery_prefix: str = "homeassistant"
    topic_prefix: str = "ohana"
    heartbeat_seconds: int = 60


@dataclass(frozen=True)
class MQTTConfig:
    """Configuration for the MQTT plugin."""

    brokers: list[MQTTBrokerConfig] = field(default_factory=list)
    timeout: float = 5.0
    retries: int = 1
    keepalive_seconds: int = 60
    client_id_prefix: str = "ohana-agent"
    topic_prefix: str = "ohana/agent/check"
    qos: int = 1
    authentication: MQTTAuthenticationConfig = field(
        default_factory=MQTTAuthenticationConfig
    )
    tls: MQTTTLSConfig = field(default_factory=MQTTTLSConfig)
    home_assistant: MQTTHomeAssistantConfig = field(
        default_factory=MQTTHomeAssistantConfig
    )
