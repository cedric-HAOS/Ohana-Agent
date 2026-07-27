"""MQTT capability check with retry support."""

from plugins.mqtt.mqtt_check_result import MQTTCheckResult
from plugins.mqtt.mqtt_client import MQTTRoundTripClient


class MQTTCheck:
    """Check an MQTT broker through a publish and receive round trip."""

    def __init__(self, client: MQTTRoundTripClient | None = None) -> None:
        self._client = client or MQTTRoundTripClient()

    def check(
        self,
        broker: str,
        *,
        port: int = 1883,
        timeout: float = 5.0,
        retries: int = 1,
        keepalive_seconds: int = 60,
        service_id: str = "mqtt",
        client_id_prefix: str = "ohana-agent",
        topic_prefix: str = "ohana/agent/check",
        qos: int = 1,
        username: str | None = None,
        password: str | None = None,
        tls_enabled: bool = False,
        ca_file: str | None = None,
        tls_insecure: bool = False,
    ) -> MQTTCheckResult:
        """Execute round trips until one succeeds or retries are exhausted."""
        if retries < 0:
            raise ValueError("retries must be greater than or equal to zero.")

        last_result = None
        attempts = 0

        for _attempt in range(retries + 1):
            attempts += 1
            last_result = self._client.roundtrip(
                broker,
                port=port,
                timeout=timeout,
                keepalive_seconds=keepalive_seconds,
                service_id=service_id,
                client_id_prefix=client_id_prefix,
                topic_prefix=topic_prefix,
                qos=qos,
                username=username,
                password=password,
                tls_enabled=tls_enabled,
                ca_file=ca_file,
                tls_insecure=tls_insecure,
            )

            if last_result.success:
                break

        if last_result is None:
            raise RuntimeError("MQTT check did not execute any request.")

        return MQTTCheckResult(
            broker=last_result.broker,
            port=last_result.port,
            healthy=last_result.success,
            topic=last_result.topic,
            qos=last_result.qos,
            client_id=last_result.client_id,
            connected=last_result.connected,
            subscribed=last_result.subscribed,
            published=last_result.published,
            received=last_result.received,
            round_trip_ms=last_result.round_trip_ms,
            tls_enabled=last_result.tls_enabled,
            attempts=attempts,
            error=last_result.error,
        )
