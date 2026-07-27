"""Build MQTT runtime configuration from declarative configuration."""

from configuration.mqtt_plugin import MQTTPluginConfig
from infrastructure import Infrastructure, Service, ServiceType
from plugins.mqtt.mqtt_config import (
    MQTTAuthenticationConfig,
    MQTTBrokerConfig,
    MQTTConfig,
    MQTTTLSConfig,
)


class MQTTConfigurationBuilder:
    """Build MQTT plugin configuration from infrastructure services."""

    def build(
        self,
        infrastructure: Infrastructure,
        config: MQTTPluginConfig,
    ) -> MQTTConfig:
        """Build an MQTTConfig from every MQTT service in the infrastructure."""
        brokers = [
            self._build_broker(service, tls_enabled=config.tls.enabled)
            for service in infrastructure.find_services(ServiceType.MQTT)
        ]

        return MQTTConfig(
            brokers=brokers,
            timeout=config.timeout,
            retries=config.retries,
            keepalive_seconds=config.keepalive_seconds,
            client_id_prefix=config.client_id_prefix,
            topic_prefix=config.topic_prefix,
            qos=config.qos,
            authentication=MQTTAuthenticationConfig(
                username=config.authentication.username,
                password=config.authentication.password,
            ),
            tls=MQTTTLSConfig(
                enabled=config.tls.enabled,
                ca_file=(
                    str(config.tls.ca_file)
                    if config.tls.ca_file is not None
                    else None
                ),
                insecure=config.tls.insecure,
            ),
        )

    @staticmethod
    def _build_broker(
        service: Service,
        *,
        tls_enabled: bool,
    ) -> MQTTBrokerConfig:
        """Convert one infrastructure MQTT service into plugin configuration."""
        if service.endpoint is None:
            raise LookupError(f"MQTT service {service.name!r} has no endpoint.")

        default_port = 8883 if tls_enabled else 1883
        port = (
            default_port
            if service.endpoint.port is None
            else service.endpoint.port
        )

        if not 1 <= port <= 65_535:
            raise ValueError(
                f"MQTT service {service.name!r} has an invalid port: {port}."
            )

        return MQTTBrokerConfig(
            name=service.name,
            address=service.endpoint.address,
            port=port,
            enabled=(service.enabled and service.endpoint.enabled),
        )
