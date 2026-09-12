"""
Ohana-Agent

Component:
    Plugins configuration

Description:
    Defines the configuration model for the plugin system.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

from pathlib import Path

from ohana_agent.configuration.base import Config


class PluginsConfig(Config):
    """Configuration model for the plugin system."""

    enabled: bool = True
    directory: Path = Path("./plugins")
