from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ohana_agent.plugins.runtime.plugin_descriptor import PluginDescriptor
from ohana_agent.plugins.runtime.plugin_manifest import PluginManifest


def test_plugin_descriptor_stores_plugin_information() -> None:
    path = Path("plugins/dns")

    descriptor = PluginDescriptor(
        name="dns",
        path=path,
    )

    assert descriptor.name == "dns"
    assert descriptor.path == path
    assert descriptor.manifest is None


def test_plugin_descriptor_can_store_manifest() -> None:
    manifest = PluginManifest(
        name="dns",
        version="1.0.0",
        author="Ohana",
        description="DNS plugin",
    )

    descriptor = PluginDescriptor(
        name="dns",
        path=Path("plugins/dns"),
        manifest=manifest,
    )

    assert descriptor.manifest is manifest


def test_plugin_descriptor_is_immutable() -> None:
    descriptor = PluginDescriptor(
        name="dns",
        path=Path("plugins/dns"),
    )

    with pytest.raises(FrozenInstanceError):
        descriptor.name = "mqtt"


def test_plugin_descriptor_uses_slots() -> None:
    descriptor = PluginDescriptor(
        name="dns",
        path=Path("plugins/dns"),
    )

    assert not hasattr(descriptor, "__dict__")
