"""Tests for the Shikamaru application runtime."""

from ohana_agent.core.application_events import (
    ApplicationStarted,
    ApplicationStopped,
    ApplicationTicked,
)
from ohana_agent.core.dispatcher import CommandDispatcher
from ohana_agent.core.events import EventBus
from ohana_agent.core.plugins import PluginManager
from ohana_agent.core.services import ServiceRegistry
from ohana_agent.persistence import MemoryManager, MemoryScope
from ohana_agent.runtime.application import Application
from ohana_agent.scheduler import DispatcherTaskExecutor, Scheduler, SchedulerStarted


def test_application_creates_service_registry() -> None:
    """Application creates a service registry."""
    app = Application()

    assert isinstance(app.services, ServiceRegistry)


def test_application_creates_core_services() -> None:
    """Application creates core services."""
    app = Application()

    assert isinstance(app.event_bus, EventBus)
    assert isinstance(app.scheduler, Scheduler)
    assert isinstance(app.plugin_manager, PluginManager)
    assert isinstance(app.command_dispatcher, CommandDispatcher)


def test_application_registers_service_registry() -> None:
    """Application registers the service registry."""
    app = Application()

    assert app.services.get(ServiceRegistry) is app.services


def test_application_registers_event_bus() -> None:
    """Application registers the event bus."""
    app = Application()

    assert app.services.get(EventBus) is app.event_bus


def test_application_registers_scheduler() -> None:
    """Application registers the scheduler."""
    app = Application()

    assert app.services.get(Scheduler) is app.scheduler


def test_application_registers_plugin_manager() -> None:
    """Application registers the plugin manager."""
    app = Application()

    assert app.services.get(PluginManager) is app.plugin_manager


def test_application_registers_command_dispatcher() -> None:
    """Application registers the command dispatcher."""
    app = Application()

    assert app.services.get(CommandDispatcher) is app.command_dispatcher


def test_application_scheduler_is_initially_stopped() -> None:
    """Application scheduler is stopped by default."""
    app = Application()

    assert app.scheduler.runtime.running is False


def test_application_scheduler_uses_dispatcher_task_executor() -> None:
    """Application scheduler uses a dispatcher task executor."""
    app = Application()

    assert isinstance(app.scheduler.executor, DispatcherTaskExecutor)


def test_application_start_starts_scheduler() -> None:
    """Application start starts the scheduler."""
    app = Application()

    app.start()

    assert app.scheduler.runtime.running is True


def test_application_stop_stops_scheduler() -> None:
    """Application stop stops the scheduler."""
    app = Application()

    app.start()
    app.stop()

    assert app.scheduler.runtime.running is False


def test_application_tick_calls_scheduler() -> None:
    """Application tick delegates to the scheduler."""
    app = Application()

    app.start()

    assert app.tick() == []


def test_application_creates_default_memory() -> None:
    app = Application()

    assert isinstance(app.memory, MemoryManager)


def test_application_uses_injected_memory() -> None:
    memory = MemoryManager()

    app = Application(memory=memory)

    assert app.memory is memory


def test_application_memory_can_store_values() -> None:
    app = Application()

    app.memory.set("temperature", 24)

    assert app.memory.get("temperature") == 24


def test_application_session_memory() -> None:
    app = Application()

    app.memory.set("user", "cedric", scope=MemoryScope.SESSION)

    assert app.memory.get("user", scope=MemoryScope.SESSION) == "cedric"


def test_application_persistent_memory() -> None:
    app = Application()

    app.memory.set("device", "pool", scope=MemoryScope.PERSISTENT)

    assert app.memory.get("device", scope=MemoryScope.PERSISTENT) == "pool"


def test_application_creates_default_event_bus() -> None:
    app = Application()

    assert isinstance(app.event_bus, EventBus)


def test_application_uses_injected_event_bus() -> None:
    event_bus = EventBus()

    app = Application(event_bus=event_bus)

    assert app.event_bus is event_bus


def test_application_start_publishes_started_event() -> None:
    event_bus = EventBus()
    received: list[ApplicationStarted] = []

    def handler(event: ApplicationStarted) -> None:
        received.append(event)

    event_bus.subscribe(ApplicationStarted, handler)

    app = Application(event_bus=event_bus)
    app.start()

    assert len(received) == 1


def test_application_stop_publishes_stopped_event() -> None:
    event_bus = EventBus()
    received: list[ApplicationStopped] = []

    def handler(event: ApplicationStopped) -> None:
        received.append(event)

    event_bus.subscribe(ApplicationStopped, handler)

    app = Application(event_bus=event_bus)
    app.stop()

    assert len(received) == 1


def test_application_tick_publishes_ticked_event() -> None:
    event_bus = EventBus()
    received: list[ApplicationTicked] = []

    def handler(event: ApplicationTicked) -> None:
        received.append(event)

    event_bus.subscribe(ApplicationTicked, handler)

    app = Application(event_bus=event_bus)
    result = app.tick()

    assert len(received) == 1
    assert received[0].result is result


def test_application_injects_event_bus_into_scheduler() -> None:
    app = Application()

    assert app.scheduler.event_bus is app.event_bus


def test_application_scheduler_publishes_events_on_start() -> None:
    app = Application()
    published_events: list[object] = []

    app.event_bus.subscribe(SchedulerStarted, published_events.append)

    app.scheduler.start()

    assert len(published_events) == 1
    assert isinstance(published_events[0], SchedulerStarted)
