"""Active MQTT round-trip client used by the MQTT plugin."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock
from time import perf_counter
from typing import Any
from uuid import uuid4

from plugins.mqtt.mqtt_result import MQTTResult


class MQTTRoundTripClient:
    """Publish a unique payload and wait for it on a unique topic."""

    def __init__(
        self,
        *,
        client_factory: Callable[[str], Any] | None = None,
        monotonic_clock: Callable[[], float] = perf_counter,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._client_factory = client_factory or self._create_paho_client
        self._monotonic_clock = monotonic_clock
        self._token_factory = token_factory or (lambda: uuid4().hex)

    def roundtrip(
        self,
        broker: str,
        *,
        port: int = 1883,
        timeout: float = 5.0,
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
    ) -> MQTTResult:
        """Perform one complete connect, subscribe, publish and receive test."""
        normalized_broker = broker.strip()

        if not normalized_broker:
            raise ValueError("broker must not be empty.")

        if isinstance(port, bool) or not 1 <= port <= 65_535:
            raise ValueError("port must be between 1 and 65535.")

        if timeout <= 0:
            raise ValueError("timeout must be greater than zero.")

        if keepalive_seconds <= 0:
            raise ValueError("keepalive_seconds must be greater than zero.")

        if isinstance(qos, bool) or qos not in {0, 1, 2}:
            raise ValueError("qos must be 0, 1 or 2.")

        token = self._token_factory()
        normalized_service_id = self._normalize_segment(service_id, "mqtt")
        normalized_client_prefix = self._normalize_segment(
            client_id_prefix,
            "ohana-agent",
        )
        normalized_topic_prefix = topic_prefix.strip().strip("/")

        if not normalized_topic_prefix:
            raise ValueError("topic_prefix must not be empty.")

        if any(character in normalized_topic_prefix for character in {"+", "#"}):
            raise ValueError("topic_prefix must not contain MQTT wildcards.")

        topic = f"{normalized_topic_prefix}/{normalized_service_id}/{token}"
        client_id = f"{normalized_client_prefix}-{normalized_service_id}-{token[:8]}"
        payload = token.encode("utf-8")

        connected_event = Event()
        subscribed_event = Event()
        received_event = Event()
        state_lock = Lock()
        state: dict[str, Any] = {
            "connected": False,
            "subscribed": False,
            "published": False,
            "received": False,
            "round_trip_ms": None,
            "error": None,
            "published_at": None,
        }

        client = None
        loop_started = False

        def on_connect(
            callback_client: Any,
            userdata: Any,
            flags: Any,
            reason_code: Any,
            properties: Any,
        ) -> None:
            del callback_client, userdata, flags, properties

            with state_lock:
                if reason_code == 0:
                    state["connected"] = True
                else:
                    state["error"] = f"MQTT connection rejected: {reason_code}."

            connected_event.set()

        def on_subscribe(
            callback_client: Any,
            userdata: Any,
            message_id: int,
            reason_codes: list[Any],
            properties: Any,
        ) -> None:
            del callback_client, userdata, message_id, properties
            rejected = any(
                bool(getattr(reason_code, "is_failure", False))
                for reason_code in reason_codes
            )

            with state_lock:
                if rejected:
                    state["error"] = "MQTT subscription was rejected by the broker."
                else:
                    state["subscribed"] = True

            subscribed_event.set()

        def on_message(
            callback_client: Any,
            userdata: Any,
            message: Any,
        ) -> None:
            del callback_client, userdata

            if message.topic != topic or bytes(message.payload) != payload:
                return

            received_at = self._monotonic_clock()

            with state_lock:
                published_at = state["published_at"]
                state["received"] = True

                if published_at is not None:
                    state["round_trip_ms"] = max(
                        0.0,
                        (received_at - published_at) * 1000,
                    )

            received_event.set()

        try:
            client = self._client_factory(client_id)
            client.on_connect = on_connect
            client.on_subscribe = on_subscribe
            client.on_message = on_message

            if username is not None:
                client.username_pw_set(username, password)

            if tls_enabled:
                client.tls_set(ca_certs=ca_file)
                client.tls_insecure_set(tls_insecure)

            connect_result = client.connect(
                normalized_broker,
                port,
                keepalive=keepalive_seconds,
            )

            if not self._successful_code(connect_result):
                raise RuntimeError(
                    f"MQTT connect request failed with code {connect_result}."
                )

            client.loop_start()
            loop_started = True

            if not connected_event.wait(timeout):
                raise TimeoutError("Timed out while connecting to the MQTT broker.")

            if state["error"] is not None:
                raise RuntimeError(str(state["error"]))

            subscribe_result, _message_id = client.subscribe(topic, qos=qos)

            if not self._successful_code(subscribe_result):
                raise RuntimeError(
                    f"MQTT subscribe request failed with code {subscribe_result}."
                )

            if not subscribed_event.wait(timeout):
                raise TimeoutError("Timed out while subscribing to the MQTT topic.")

            if state["error"] is not None:
                raise RuntimeError(str(state["error"]))

            with state_lock:
                state["published_at"] = self._monotonic_clock()

            publish_info = client.publish(topic, payload, qos=qos, retain=False)

            if not self._successful_code(publish_info.rc):
                raise RuntimeError(
                    f"MQTT publish request failed with code {publish_info.rc}."
                )

            with state_lock:
                state["published"] = True

            if not received_event.wait(timeout):
                raise TimeoutError(
                    "Timed out while waiting for the MQTT round-trip message."
                )

            return MQTTResult(
                broker=normalized_broker,
                port=port,
                success=True,
                topic=topic,
                qos=qos,
                client_id=client_id,
                connected=bool(state["connected"]),
                subscribed=bool(state["subscribed"]),
                published=bool(state["published"]),
                received=bool(state["received"]),
                round_trip_ms=state["round_trip_ms"],
                tls_enabled=tls_enabled,
            )
        except Exception as error:
            return MQTTResult(
                broker=normalized_broker,
                port=port,
                success=False,
                topic=topic,
                qos=qos,
                client_id=client_id,
                connected=bool(state["connected"]),
                subscribed=bool(state["subscribed"]),
                published=bool(state["published"]),
                received=bool(state["received"]),
                round_trip_ms=state["round_trip_ms"],
                tls_enabled=tls_enabled,
                error=str(error),
            )
        finally:
            if client is not None:
                try:
                    client.unsubscribe(topic)
                except Exception:
                    pass

                try:
                    client.disconnect()
                except Exception:
                    pass

                if loop_started:
                    try:
                        client.loop_stop()
                    except Exception:
                        pass

    @staticmethod
    def _create_paho_client(client_id: str) -> Any:
        try:
            from paho.mqtt import client as mqtt
        except ImportError as error:
            raise RuntimeError(
                "The paho-mqtt dependency is required by the MQTT plugin."
            ) from error

        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )

    @staticmethod
    def _normalize_segment(value: str, fallback: str) -> str:
        normalized = value.strip().replace("/", "-").replace("+", "-")
        normalized = normalized.replace("#", "-").replace(" ", "-")
        return normalized or fallback

    @staticmethod
    def _successful_code(code: Any) -> bool:
        try:
            return int(code) == 0
        except (TypeError, ValueError):
            return code == 0

