from ohana_agent.plugins.runtime.plugin_runtime import PluginRuntime
from ohana_agent.plugins.runtime.plugin_state import PluginState


def test_plugin_runtime_is_empty_by_default() -> None:
    runtime = PluginRuntime()

    assert runtime.count == 0
    assert runtime.plugins == ()


def test_plugin_runtime_sets_plugin_state() -> None:
    runtime = PluginRuntime()

    runtime.set_state("dns", PluginState.LOADED)

    assert runtime.state("dns") == PluginState.LOADED


def test_plugin_runtime_returns_none_for_unknown_plugin() -> None:
    runtime = PluginRuntime()

    assert runtime.state("unknown") is None


def test_plugin_runtime_has_plugin_state() -> None:
    runtime = PluginRuntime()

    runtime.set_state("dns", PluginState.REGISTERED)

    assert runtime.has("dns") is True


def test_plugin_runtime_does_not_have_unknown_plugin() -> None:
    runtime = PluginRuntime()

    assert runtime.has("unknown") is False


def test_plugin_runtime_can_overwrite_plugin_state() -> None:
    runtime = PluginRuntime()

    runtime.set_state("dns", PluginState.DISCOVERED)
    runtime.set_state("dns", PluginState.REGISTERED)

    assert runtime.state("dns") == PluginState.REGISTERED


def test_plugin_runtime_removes_plugin_state() -> None:
    runtime = PluginRuntime()

    runtime.set_state("dns", PluginState.REGISTERED)
    runtime.remove("dns")

    assert runtime.has("dns") is False
    assert runtime.state("dns") is None


def test_plugin_runtime_remove_unknown_plugin_is_noop() -> None:
    runtime = PluginRuntime()

    runtime.remove("unknown")

    assert runtime.count == 0


def test_plugin_runtime_clears_all_states() -> None:
    runtime = PluginRuntime()

    runtime.set_state("dns", PluginState.REGISTERED)
    runtime.set_state("mqtt", PluginState.FAILED)

    runtime.clear()

    assert runtime.count == 0
    assert runtime.plugins == ()


def test_plugin_runtime_returns_plugin_names() -> None:
    runtime = PluginRuntime()

    runtime.set_state("dns", PluginState.REGISTERED)
    runtime.set_state("mqtt", PluginState.LOADED)

    assert runtime.plugins == ("dns", "mqtt")
