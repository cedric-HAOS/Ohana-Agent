"""
Ohana-Agent

Component:
    Agent configuration

Description:
    Defines the configuration model for the agent identity.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

from ohana_agent.configuration.base import Config
from ohana_agent.configuration.enums import Environment


class AgentConfig(Config):
    """Configuration model for the agent identity."""

    name: str = "Shikamaru"
    environment: Environment = Environment.DEVELOPMENT
