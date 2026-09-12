from ohana_agent.plugins.runtime import Plugin


def test_plugin_exposes_execute_method() -> None:
    assert hasattr(Plugin, "execute")
