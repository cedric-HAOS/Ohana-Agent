"""
Ohana-Agent

Component:
    Health configuration

Description:
    Defines the configuration model for the health monitoring component.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

from pydantic import PositiveInt

from ohana_agent.configuration.base import Config


class HealthConfig(Config):
    """Configuration model for health monitoring."""

    enabled: bool = True
    interval_seconds: PositiveInt = 30
