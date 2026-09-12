from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol


class MQTTConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"


class MQTTClientError(Exception):
    """Base exception for MQTT client errors."""


class MQTTClientNotConnectedError(MQTTClientError):
    """Raised when an MQTT operation requires an active connection."""


class MQTTTransport(Protocol):
    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...


class MQTTPublisher(Protocol):
    async def publish(
        self,
        topic: str,
        payload: object,
        *,
        qos: int,
        retain: bool,
    ) -> None: ...


class MQTTSubscriber(Protocol):
    async def subscribe(self, topic: str) -> None: ...

    async def unsubscribe(self, topic: str) -> None: ...


class MQTTClient:
    """Facade for MQTT runtime operations."""

    def __init__(
        self,
        config: Any,
        transport: MQTTTransport,
        publisher: MQTTPublisher,
        subscriber: MQTTSubscriber,
    ) -> None:
        self.config = config
        self.transport = transport
        self.publisher = publisher
        self.subscriber = subscriber

        self.state = MQTTConnectionState.DISCONNECTED
        self._subscriptions: set[str] = set()

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.config, "enabled", True))

    @property
    def is_connected(self) -> bool:
        return self.state == MQTTConnectionState.CONNECTED

    @property
    def qos(self) -> int:
        return int(getattr(self.config, "qos", 0))

    @property
    def retain(self) -> bool:
        return bool(getattr(self.config, "retain", False))

    async def connect(self) -> None:
        if not self.enabled:
            return

        if self.is_connected:
            return

        self.state = MQTTConnectionState.CONNECTING

        try:
            await self.transport.connect()
            self.state = MQTTConnectionState.CONNECTED
            await self._restore_subscriptions()
        except Exception:
            self.state = MQTTConnectionState.DISCONNECTED
            raise

    async def disconnect(self) -> None:
        if not self.is_connected:
            self.state = MQTTConnectionState.DISCONNECTED
            return

        self.state = MQTTConnectionState.DISCONNECTING

        try:
            await self.transport.disconnect()
        finally:
            self.state = MQTTConnectionState.DISCONNECTED

    async def publish(self, topic: str, payload: object) -> None:
        self._ensure_connected()

        await self.publisher.publish(
            topic,
            payload,
            qos=self.qos,
            retain=self.retain,
        )

    async def subscribe(self, topic: str) -> None:
        self._subscriptions.add(topic)

        if self.is_connected:
            await self.subscriber.subscribe(topic)

    async def unsubscribe(self, topic: str) -> None:
        self._subscriptions.discard(topic)

        if self.is_connected:
            await self.subscriber.unsubscribe(topic)

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise MQTTClientNotConnectedError("MQTT client is not connected.")

    async def _restore_subscriptions(self) -> None:
        for topic in sorted(self._subscriptions):
            await self.subscriber.subscribe(topic)
