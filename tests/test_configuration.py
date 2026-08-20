"""
Ohana-Agent

Component:
    Configuration tests

Description:
    Tests the configuration loading chain.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from configuration.enums import Environment, LogLevel
from configuration.loader import ConfigurationLoader


def test_load_shikamaru_configuration() -> None:
    """Load the default Shikamaru YAML configuration."""
    configuration = ConfigurationLoader.load(Path("config/shikamaru.yaml"))

    assert configuration.version == 1
    assert configuration.agent.name == "Shikamaru"
    assert configuration.agent.environment == Environment.PRODUCTION
    assert configuration.mqtt.host == "ha-green.ohana.lan"
    assert configuration.mqtt.port == 1883
    assert configuration.logging.level == LogLevel.INFO
    assert configuration.health.enabled is True
    assert configuration.health.interval_seconds == 30
    assert configuration.plugins.enabled is True
    assert str(configuration.plugins.directory) == "plugins"
    assert configuration.vision.enabled is True
    assert str(configuration.vision.observation_url) == (
        "http://127.0.0.1:8000/api/observations"
    )
    assert str(configuration.vision.infrastructure_url) == (
        "http://127.0.0.1:8000/api/infrastructure"
    )
    assert configuration.vision.timeout_seconds == 5.0
    assert configuration.vision.infrastructure_retry_seconds == 10.0
    assert configuration.vision.infrastructure_refresh_seconds == 300.0
    assert configuration.vision.outbox_path is None
    assert configuration.vision.outbox_retry_seconds == 10.0
    assert configuration.vision.outbox_max_entries == 50_000


def test_configuration_accepts_schema_version_one(
    tmp_path: Path,
) -> None:
    """Accept the supported configuration schema version."""
    config_path = tmp_path / "shikamaru.yaml"
    config_path.write_text(
        "version: 1\n",
        encoding="utf-8",
    )

    configuration = ConfigurationLoader.load(config_path)

    assert configuration.version == 1


def test_configuration_rejects_unknown_schema_version(
    tmp_path: Path,
) -> None:
    """Reject a configuration schema version not supported by the agent."""
    config_path = tmp_path / "shikamaru.yaml"
    config_path.write_text(
        "version: 2\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="version"):
        ConfigurationLoader.load(config_path)


def test_configuration_uses_schema_version_one_by_default(
    tmp_path: Path,
) -> None:
    """Use schema version one when the version field is omitted."""
    config_path = tmp_path / "shikamaru.yaml"
    config_path.write_text(
        "{}\n",
        encoding="utf-8",
    )

    configuration = ConfigurationLoader.load(config_path)

    assert configuration.version == 1


def test_configuration_loader_accepts_string_path() -> None:
    """Accept a string configuration path."""
    configuration = ConfigurationLoader.load("config/shikamaru.yaml")

    assert configuration.version == 1


def test_configuration_loader_raises_for_missing_file(
    tmp_path: Path,
) -> None:
    """Preserve FileNotFoundError for a missing configuration file."""
    missing_path = tmp_path / "missing.yaml"

    with pytest.raises(FileNotFoundError):
        ConfigurationLoader.load(missing_path)


def test_configuration_loader_raises_for_invalid_yaml(
    tmp_path: Path,
) -> None:
    """Preserve the YAML parsing error for malformed configuration."""
    config_path = tmp_path / "shikamaru.yaml"
    config_path.write_text(
        "version: [\n",
        encoding="utf-8",
    )

    with pytest.raises(yaml.YAMLError):
        ConfigurationLoader.load(config_path)


def test_configuration_loader_rejects_non_mapping_yaml(
    tmp_path: Path,
) -> None:
    """Reject a YAML document that is not an object."""
    config_path = tmp_path / "shikamaru.yaml"
    config_path.write_text(
        "- version\n- agent\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        ConfigurationLoader.load(config_path)
