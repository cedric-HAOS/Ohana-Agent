"""
Ohana-Agent

Component:
    Configuration

Description:
    Defines the root configuration model.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ohana_agent.configuration.administration import AdministrationConfig
from ohana_agent.configuration.agent import AgentConfig
from ohana_agent.configuration.base import Config
from ohana_agent.configuration.health import HealthConfig
from ohana_agent.configuration.logging import LoggingConfig
from ohana_agent.configuration.mqtt import MQTTConfig
from ohana_agent.configuration.plugins import PluginsConfig
from ohana_agent.configuration.vision import VisionConfig


class Configuration(Config):
    """Root configuration model."""

    version: Literal[1] = 1

    agent: AgentConfig = Field(default_factory=AgentConfig)
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    administration: AdministrationConfig = Field(default_factory=AdministrationConfig)
