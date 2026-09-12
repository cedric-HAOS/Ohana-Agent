from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


class MQTTBackendSubscriber(Protocol):
    async def subscribe(self, topic: str) -> None: ...

    async def unsubscribe(self, topic: str) -> None: ...


class MQTTDispatcher(Protocol):
    async def dispatch(self, event: object) -> None: ...


@dataclass(frozen=True)
class MQTTMessageReceivedEvent:
    topic: str
    payload: object


class MQTTSubscriber:
    """Receive MQTT messages and forward them as internal events."""

    def __init__(
        self,
        backend: MQTTBackendSubscriber,
        dispatcher: MQTTDispatcher,
    ) -> None:
        self.backend = backend
        self.dispatcher = dispatcher

    async def subscribe(self, topic: str) -> None:
        await self.backend.subscribe(topic)

    async def unsubscribe(self, topic: str) -> None:
        await self.backend.unsubscribe(topic)

    async def handle_message(self, topic: str, payload: str | bytes) -> None:
        decoded_payload = self.deserialize(payload)

        event = MQTTMessageReceivedEvent(
            topic=topic,
            payload=decoded_payload,
        )

        await self.dispatcher.dispatch(event)

    def deserialize(self, payload: str | bytes) -> Any:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")

        return json.loads(payload)
