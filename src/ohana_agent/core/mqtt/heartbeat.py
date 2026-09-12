from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ohana_agent.core.mqtt.messages import (
    MQTTAvailabilityMessage,
    MQTTAvailabilityStatus,
    MQTTHealthStatus,
    MQTTStatusMessage,
)


class MQTTHeartbeatPublisher(Protocol):
    async def publish(
        self,
        topic: str,
        payload: object,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None: ...


@dataclass(frozen=True)
class MQTTHeartbeatConfig:
    agent_name: str = "shikamaru"
    base_topic: str = "ohana/agent/shikamaru"
    version: str = "0.3.0"
    qos: int = 1
    retain: bool = False


class MQTTHeartbeatService:
    """Publish MQTT heartbeat and availability messages."""

    def __init__(
        self,
        config: MQTTHeartbeatConfig,
        publisher: MQTTHeartbeatPublisher,
    ) -> None:
        self.config = config
        self.publisher = publisher

    @property
    def status_topic(self) -> str:
        return f"{self.config.base_topic}/status"

    @property
    def availability_topic(self) -> str:
        return f"{self.config.base_topic}/availability"

    def build_status_message(
        self,
        *,
        state: str,
        health: MQTTHealthStatus,
        uptime_seconds: int,
    ) -> MQTTStatusMessage:
        return MQTTStatusMessage.create(
            agent=self.config.agent_name,
            state=state,
            health=health,
            uptime=uptime_seconds,
            version=self.config.version,
        )

    def build_availability_message(
        self,
        status: MQTTAvailabilityStatus,
    ) -> MQTTAvailabilityMessage:
        return MQTTAvailabilityMessage(status=status)

    async def publish_heartbeat_once(
        self,
        *,
        state: str,
        health: MQTTHealthStatus,
        uptime_seconds: int,
    ) -> None:
        message = self.build_status_message(
            state=state,
            health=health,
            uptime_seconds=uptime_seconds,
        )

        await self.publisher.publish(
            self.status_topic,
            message.to_dict(),
            qos=self.config.qos,
            retain=self.config.retain,
        )

    async def publish_online(self) -> None:
        message = self.build_availability_message(
            MQTTAvailabilityStatus.ONLINE,
        )

        await self.publisher.publish(
            self.availability_topic,
            message.to_dict(),
            qos=self.config.qos,
            retain=True,
        )

    async def publish_offline(self) -> None:
        message = self.build_availability_message(
            MQTTAvailabilityStatus.OFFLINE,
        )

        await self.publisher.publish(
            self.availability_topic,
            message.to_dict(),
            qos=self.config.qos,
            retain=True,
        )
