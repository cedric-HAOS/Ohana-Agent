"""Tests for base capability contract."""

import pytest

from ohana_agent.core.capability.base import BaseCapability


def test_base_capability_cannot_be_instantiated() -> None:
    """BaseCapability is abstract and cannot be instantiated."""

    with pytest.raises(TypeError):
        BaseCapability()
