from ohana_agent.plugins.dns.plugin import DNSPlugin
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_runtime import PluginState


class FakeEventBus:
    """Fake event bus used by DNS plugin registration tests."""

    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def make_context(
    event_bus: FakeEventBus | None = None,
) -> PluginContext:
    """Build a minimal plugin context."""
    return PluginContext(
        event_bus=event_bus or FakeEventBus(),
        scheduler=object(),
        dispatcher=object(),
        memory=object(),
        capability_manager=object(),
        configuration=object(),
        runtime=object(),
    )


def test_dns_plugin_has_name() -> None:
    plugin = DNSPlugin()

    assert plugin.name == "dns"


def test_dns_plugin_initial_state_is_loaded() -> None:
    plugin = DNSPlugin()

    assert plugin.state is PluginState.LOADED


def test_dns_plugin_manifest() -> None:
    plugin = DNSPlugin()

    manifest = plugin.manifest

    assert manifest.name == "dns"
    assert manifest.version == "0.1.0"
    assert manifest.description == ("DNS capability plugin for Ohana-Agent.")


def test_dns_plugin_register_sets_registered_state() -> None:
    plugin = DNSPlugin()
    context = make_context()

    plugin.register(context)

    assert plugin.state is PluginState.REGISTERED


def test_dns_plugin_register_uses_context_event_bus() -> None:
    event_bus = FakeEventBus()
    plugin = DNSPlugin()
    context = make_context(event_bus)

    plugin.register(context)

    plugin.check("example.com")

    assert len(event_bus.events) >= 1
