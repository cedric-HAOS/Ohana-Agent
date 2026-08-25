"""
Ohana-Agent

Component:
    Configuration loader

Description:
    Loads the application configuration from a YAML file.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

from pathlib import Path

import yaml

from configuration.configuration import Configuration


class ConfigurationLoader:
    """Loads the application configuration."""

    @staticmethod
    def load(path: str | Path) -> Configuration:
        """
        Load a configuration from a YAML file.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            A validated Configuration instance.
        """
        file_path = Path(path)

        with file_path.open("r", encoding="utf-8") as config_file:
            data = yaml.safe_load(config_file) or {}

        return Configuration.model_validate(data)

    @staticmethod
    def write_wake_on_lan_enabled(path: str | Path, enabled: bool) -> None:
        """Persist only the Agent-owned Wake-on-LAN activation flag."""
        file_path = Path(path)

        with file_path.open("r", encoding="utf-8") as config_file:
            data = yaml.safe_load(config_file) or {}

        administration = data.setdefault("administration", {})
        jobs = administration.setdefault("jobs", {})
        wake_on_lan = jobs.setdefault("wake_on_lan", {})
        wake_on_lan["enabled"] = enabled

        file_path.write_text(
            yaml.safe_dump(
                data,
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
