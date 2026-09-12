"""
Ohana-Agent

Component:
    Configuration model

Description:
    Defines the base model for all configuration sections.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    """Base model for all configuration sections."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )
