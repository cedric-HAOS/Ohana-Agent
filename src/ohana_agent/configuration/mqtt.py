"""
Ohana-Agent

Component:
    MQTT configuration

Description:
    Defines the configuration model for MQTT connectivity.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

from pydantic import PositiveInt

from ohana_agent.configuration.base import Config


class MQTTAuthenticationConfig(Config):
    """Configuration model for MQTT authentication."""

    username: str | None = None
    password: str | None = None


class MQTTConfig(Config):
    """Configuration model for MQTT connectivity."""

    host: str = "localhost"
    port: PositiveInt = 1883
    client_id: str | None = None
    keepalive_seconds: PositiveInt = 60
    authentication: MQTTAuthenticationConfig = MQTTAuthenticationConfig()
