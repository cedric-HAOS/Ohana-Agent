"""Persistence for the Agent-owned infrastructure configuration."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.configuration.infrastructure_validator import InfrastructureValidator
from ohana_agent.configuration.loaders import InfrastructureLoader


class InfrastructureConfigurationRepository:
    """Validate and atomically persist infrastructure configuration."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> InfrastructureConfig:
        """Load the current Agent-owned infrastructure document."""
        return InfrastructureLoader().load(self.path)

    def write(
        self,
        configuration: InfrastructureConfig,
    ) -> InfrastructureConfig:
        """Validate and atomically replace the infrastructure document."""
        InfrastructureValidator().validate(configuration)
        payload: dict[str, Any] = configuration.model_dump(
            mode="json",
            exclude_none=True,
        )
        content = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
        )

        temporary_path: Path | None = None

        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
                delete=False,
            ) as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)

            os.replace(
                temporary_path,
                self.path,
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        return self.read()
