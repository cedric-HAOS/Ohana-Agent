"""
Ohana-Agent

Component:
    Logging configuration

Description:
    Defines the configuration model for application logging.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

from ohana_agent.configuration.base import Config
from ohana_agent.configuration.enums import LogLevel


class LoggingConfig(Config):
    """Configuration model for application logging."""

    level: LogLevel = LogLevel.INFO
