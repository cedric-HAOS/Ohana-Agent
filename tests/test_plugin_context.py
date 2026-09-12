from dataclasses import FrozenInstanceError

import pytest

from ohana_agent.plugins.runtime.plugin_context import PluginContext


def test_plugin_context_stores_services() -> None:
    scheduler = object()

    context = PluginContext(
        event_bus=object(),
        scheduler=scheduler,
        dispatcher=object(),
        memory=object(),
        capability_manager=object(),
        configuration=object(),
        runtime=object(),
    )

    assert context.scheduler is scheduler


def test_plugin_context_is_immutable() -> None:
    context = PluginContext(
        event_bus=object(),
        scheduler=object(),
        dispatcher=object(),
        memory=object(),
        capability_manager=object(),
        configuration=object(),
        runtime=object(),
    )

    with pytest.raises(FrozenInstanceError):
        context.scheduler = object()
