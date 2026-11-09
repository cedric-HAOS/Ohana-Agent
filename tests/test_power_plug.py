"""Smart plug: powered before a wake, cut only once the PC is demonstrably off."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from ohana_agent.api.service import AdministrationService
from ohana_agent.configuration.loaders.power_plug import PowerPlugConfigLoader
from ohana_agent.configuration.power_plug import PowerPlugPluginConfig
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.jobs.power_plug import (
    PlugPolicy,
    PlugReading,
    PowerPlugController,
    PowerPlugError,
)
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.plugins.administration import (
    PluginAdministrationBinding,
    PluginAdministrationRepository,
)
from ohana_agent.plugins.power_plug.client import HomeAssistantPlug
from ohana_agent.plugins.power_plug.plugin import PowerPlugPlugin
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_manager import PluginManager
from ohana_agent.scheduler import Scheduler
from ohana_agent.scheduler.clock import FakeClock

WORKER = "katsuyu-bubule"
SWITCH = "switch.shellyplugsg3_80b54e297538"
MAC = "AA:BB:CC:DD:EE:FF"
REGISTRATION: dict[str, object] = {
    "protocol_version": 1,
    "worker_id": WORKER,
    "capabilities": ["system.health"],
    "platform": "Windows 11",
    "worker_version": "0.14.2",
    "wake_on_lan_mac_address": MAC,
}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 10, 4, 59, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakePlug:
    """What the plug says and what it was told."""

    def __init__(self, *, on: bool = False, watts: float | None = None) -> None:
        self.on = on
        self.watts = watts
        self.calls: list[str] = []
        self.failing: set[str] = set()

    def read(self) -> PlugReading:
        if "read" in self.failing:
            raise PowerPlugError("Home Assistant unreachable (down)")
        return PlugReading(self.on, self.watts)

    def turn_on(self) -> None:
        if "on" in self.failing:
            raise PowerPlugError("Home Assistant answered HTTP 500")
        self.calls.append("on")
        self.on = True

    def turn_off(self) -> None:
        if "off" in self.failing:
            raise PowerPlugError("Home Assistant answered HTTP 500")
        self.calls.append("off")
        self.on = False


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def repository(tmp_path: Path, clock: Clock) -> DistributedJobRepository:
    instance = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    yield instance
    instance.close()


def _build(
    tmp_path: Path,
    repository: DistributedJobRepository,
    plug: FakePlug,
    wakes: list[str],
    **policy: Any,
) -> tuple[AdministrationService, PowerPlugController]:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(
        "infrastructure:\n  id: ohana-house\n  name: Ohana House\n"
        "  environment: production\nnodes: []\nservices: []\n",
        encoding="utf-8",
    )
    controller = PowerPlugController(
        plug, repository, policy=lambda: PlugPolicy(**policy)
    )
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        wake_enabled=True,
        wake_sender=wakes.append,
        wake_minimum_interval_seconds=0,
        wake_worker_id=WORKER,
        power_plug=controller,
    )
    return service, controller


def _queue_work(repository: DistributedJobRepository, clock: Clock) -> None:
    repository.register_worker(REGISTRATION)
    clock.advance(3600)
    repository.create(
        {
            "protocol_version": 1,
            "job_id": "20000000-0000-4000-8000-000000000001",
            "type": "system.health",
            "created_at": clock.now.isoformat(),
            "parameters": {},
            "timeout": 3600,
        }
    )


def _kinds(repository: DistributedJobRepository) -> list[str]:
    events = repository.list_workers().workers[0].power_events
    return [event.kind.value for event in reversed(events)]


def _shutdown_started(repository: DistributedJobRepository) -> None:
    repository.report_worker_power(
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "outcome": "shutdown_started",
        }
    )


def _wake_and_boot(
    service: AdministrationService,
    repository: DistributedJobRepository,
    clock: Clock,
) -> None:
    """A wake that works: the PC is powered, woken, and Katsuyu registers."""
    assert service._wake_compatible_worker("system.health")  # noqa: SLF001
    clock.advance(20)
    service.tick_power_plug(clock.now)
    clock.advance(40)
    repository.register_worker(REGISTRATION)


# -- before a wake -----------------------------------------------------------


def test_an_unpowered_pc_gets_power_first_and_the_packet_follows(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False)
    service, _ = _build(tmp_path, repository, plug, wakes, boot_delay_seconds=15)
    _queue_work(repository, clock)

    assert service._wake_compatible_worker("system.health")  # noqa: SLF001

    assert plug.calls == ["on"]
    assert wakes == []  # not yet: the PC has had no power
    assert repository.plug_turned_on_at() == clock.now
    clock.advance(14)
    service.tick_power_plug(clock.now)
    assert wakes == []
    clock.advance(2)
    service.tick_power_plug(clock.now)
    assert wakes == [MAC]
    service.tick_power_plug(clock.now + timedelta(seconds=5))
    assert wakes == [MAC]  # one packet burst per wake

    assert _kinds(repository) == ["plug_on", "wake_sent"]
    sent = repository.list_workers().workers[0].power_events[0]
    assert sent.detail["plug"] == "turned_on"
    assert sent.detail["wol_delay_seconds"] == 15
    assert sent.detail["trigger"] == "queued_jobs"


def test_a_powered_pc_is_woken_at_once_and_the_plug_left_alone(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=True)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)

    assert service._wake_compatible_worker("system.health")  # noqa: SLF001

    assert wakes == [MAC]
    assert plug.calls == []
    assert repository.plug_turned_on_at() is None
    assert _kinds(repository) == ["wake_sent"]
    sent = repository.list_workers().workers[0].power_events[0]
    assert sent.detail["plug"] == "already_on"


@pytest.mark.parametrize("failing", ["read", "on"])
def test_an_unusable_plug_never_blocks_the_wake(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock, failing: str
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False)
    plug.failing.add(failing)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)

    assert service._wake_compatible_worker("system.health")  # noqa: SLF001

    # Exactly the behaviour before the plug existed.
    assert wakes == [MAC]
    assert repository.plug_turned_on_at() is None
    assert _kinds(repository) == ["plug_failed", "wake_sent"]
    failure = repository.list_workers().workers[0].power_events[1]
    assert failure.detail["action"] == ("read" if failing == "read" else "on")
    # The plug event does not hide the wake from the unanswered-wake rules.
    clock.advance(181)
    assert repository.list_workers().workers[0].power_events[0].kind.value == (
        "wake_timeout"
    )


def test_a_pc_that_booted_alone_when_the_power_came_back_gets_no_packet(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    service, _ = _build(tmp_path, repository, FakePlug(on=False), wakes)
    _queue_work(repository, clock)
    service._wake_compatible_worker("system.health")  # noqa: SLF001

    clock.advance(10)
    repository.register_worker(REGISTRATION)  # BIOS "power on after AC loss"
    clock.advance(10)
    service.tick_power_plug(clock.now)

    assert wakes == []
    assert "worker_online" in _kinds(repository)


def test_a_manual_wake_test_powers_the_plug_too(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False)
    service, _ = _build(tmp_path, repository, plug, wakes)
    repository.register_worker(REGISTRATION)
    clock.advance(3600)

    document = service.wake_worker(WORKER)

    assert plug.calls == ["on"]
    assert wakes == []
    assert document.availability.value == "WAKING"
    clock.advance(16)
    service.tick_power_plug(clock.now)
    assert wakes == [MAC]


# -- after a cycle -------------------------------------------------------------


def test_the_plug_is_cut_once_the_pc_draws_nothing(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False, watts=30.0)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)
    _wake_and_boot(service, repository, clock)
    _shutdown_started(repository)

    # Windows is still shutting down: the load is high, the worker still polls.
    for _ in range(4):
        clock.advance(20)
        service.tick_power_plug(clock.now)
    assert "off" not in plug.calls

    plug.watts = 0.8  # off
    cut_at = None
    for _ in range(8):
        clock.advance(20)
        service.tick_power_plug(clock.now)
        if "off" in plug.calls and cut_at is None:
            cut_at = clock.now
    assert plug.calls == ["on", "off"]
    assert repository.plug_turned_on_at() is None
    assert _kinds(repository)[-2:] == ["shutdown_started", "plug_off"]
    off = repository.list_workers().workers[0].power_events[0]
    assert off.detail["reason"] == "shutdown_started"
    assert off.detail["watts"] == 0.8
    assert off.detail["idle_seconds"] >= 30

    # Cut once: later ticks leave it alone, even if someone switches it on again.
    plug.on = True
    plug.calls.clear()
    for _ in range(10):
        clock.advance(20)
        service.tick_power_plug(clock.now)
    assert plug.calls == []


def test_a_load_that_comes_back_restarts_the_idle_wait(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False, watts=0.5)
    service, _ = _build(tmp_path, repository, plug, wakes, poll_seconds=5)
    _queue_work(repository, clock)
    _wake_and_boot(service, repository, clock)
    _shutdown_started(repository)
    clock.advance(40)  # the worker stops polling: unavailable

    service.tick_power_plug(clock.now)  # idle seen once
    clock.advance(20)
    plug.watts = 45.0  # Windows installs an update at shutdown
    service.tick_power_plug(clock.now)
    clock.advance(20)
    plug.watts = 0.5
    service.tick_power_plug(clock.now)  # idle again, wait restarts

    assert "off" not in plug.calls
    clock.advance(31)
    service.tick_power_plug(clock.now)
    assert plug.calls == ["on", "off"]


def test_without_a_power_reading_the_plug_waits_for_the_grace_period(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False, watts=None)
    service, _ = _build(tmp_path, repository, plug, wakes, shutdown_grace_seconds=300)
    _queue_work(repository, clock)
    _wake_and_boot(service, repository, clock)
    _shutdown_started(repository)

    clock.advance(240)
    service.tick_power_plug(clock.now)
    assert plug.calls == ["on"]
    clock.advance(70)
    service.tick_power_plug(clock.now)
    assert plug.calls == ["on", "off"]


def test_a_pc_kept_on_by_a_veto_keeps_its_power(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False, watts=0.5)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)
    _wake_and_boot(service, repository, clock)
    repository.report_worker_power(
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "outcome": "shutdown_vetoed",
            "reason": "interactive_session",
            "sessions": 1,
        }
    )

    # Katsuyu keeps polling: the PC is up, whatever the plug measures.
    for _ in range(10):
        clock.advance(10)
        repository.register_worker(REGISTRATION)
        service.tick_power_plug(clock.now)
    assert "off" not in plug.calls


def test_a_vetoed_pc_is_cut_when_it_is_later_switched_off_by_hand(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False, watts=60.0)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)
    _wake_and_boot(service, repository, clock)
    repository.report_worker_power(
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "outcome": "shutdown_vetoed",
            "reason": "interactive_session",
            "sessions": 1,
        }
    )
    clock.advance(3600)  # the user shuts the PC down, Katsuyu is gone

    plug.watts = 0.4
    for _ in range(6):
        clock.advance(20)
        service.tick_power_plug(clock.now)

    assert plug.calls == ["on", "off"]
    assert repository.list_workers().workers[0].power_events[0].detail["reason"] == (
        "worker_offline"
    )


def test_a_plug_the_user_switched_on_is_not_cut_without_a_reason(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=True, watts=0.4)
    service, _ = _build(tmp_path, repository, plug, wakes)
    repository.register_worker(REGISTRATION)
    clock.advance(3600)  # the PC is off, nothing was woken by Ohana

    for _ in range(10):
        clock.advance(20)
        service.tick_power_plug(clock.now)

    assert plug.calls == []


def test_a_plug_that_was_already_on_stays_on_after_a_shutdown_ohana_ran(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=True, watts=20.0)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)
    _wake_and_boot(service, repository, clock)  # plug already on: not Ohana's
    _shutdown_started(repository)
    plug.watts = 0.6

    for _ in range(30):
        clock.advance(20)
        service.tick_power_plug(clock.now)

    assert plug.calls == []
    assert "plug_off" not in _kinds(repository)


def test_a_pc_the_owner_started_and_stopped_keeps_its_plug(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    """9 November, real: an old Ohana shutdown must not justify a cut days later."""
    wakes: list[str] = []
    plug = FakePlug(on=True, watts=20.0)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)
    _wake_and_boot(service, repository, clock)  # the 05:00 cycle, plug already on
    _shutdown_started(repository)
    clock.advance(6 * 3600)

    repository.register_worker(REGISTRATION)  # the owner starts the PC by hand
    plug.watts = 166.6
    for _ in range(5):
        clock.advance(20)
        repository.register_worker(REGISTRATION)
        service.tick_power_plug(clock.now)
    plug.watts = 0.5  # ... and shuts it down by hand
    for _ in range(30):
        clock.advance(20)
        service.tick_power_plug(clock.now)

    assert plug.calls == []
    assert "plug_off" not in _kinds(repository)


def test_a_silent_pc_is_unplugged_again_only_when_it_draws_nothing(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False, watts=0.5)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)
    service._wake_compatible_worker("system.health")  # noqa: SLF001
    for _ in range(3):
        clock.advance(181)
        service.dispatch_due_wake_requests(clock.now)
        clock.advance(600)
        service.dispatch_due_wake_requests(clock.now)
    assert "wake_abandoned" in _kinds(repository)
    plug.calls.clear()
    for _ in range(6):
        clock.advance(20)
        service.tick_power_plug(clock.now)

    assert plug.calls == ["off"]  # drew nothing: it never booted
    assert repository.list_workers().workers[0].power_events[0].detail["reason"] == (
        "wake_abandoned"
    )


def test_a_silent_pc_without_a_reading_keeps_its_power(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False, watts=None)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)
    service._wake_compatible_worker("system.health")  # noqa: SLF001
    for _ in range(3):
        clock.advance(181)
        service.dispatch_due_wake_requests(clock.now)
        clock.advance(600)
        service.dispatch_due_wake_requests(clock.now)
    for _ in range(40):
        clock.advance(60)
        service.tick_power_plug(clock.now)

    # It may be running with a dead worker: cutting could kill Windows mid-write.
    assert "off" not in plug.calls


def test_a_wake_still_due_a_retry_keeps_the_plug_on(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False, watts=0.5)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)
    service._wake_compatible_worker("system.health")  # noqa: SLF001
    clock.advance(200)  # first wait expired, retry due in 10 minutes
    for _ in range(5):
        clock.advance(20)
        service.tick_power_plug(clock.now)

    assert "off" not in plug.calls


def test_a_failing_cut_is_retried_and_reported_once(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False, watts=30.0)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)
    _wake_and_boot(service, repository, clock)
    _shutdown_started(repository)
    plug.watts = 0.5
    plug.failing.add("off")

    for _ in range(12):
        clock.advance(20)
        service.tick_power_plug(clock.now)
    failures = [k for k in _kinds(repository) if k == "plug_failed"]
    assert len(failures) == 1

    plug.failing.clear()
    for _ in range(3):
        clock.advance(20)
        service.tick_power_plug(clock.now)
    assert plug.calls[-1] == "off"
    assert _kinds(repository)[-1] == "plug_off"


def test_a_plug_already_off_is_recorded_without_a_command(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False, watts=30.0)
    service, _ = _build(tmp_path, repository, plug, wakes)
    _queue_work(repository, clock)
    _wake_and_boot(service, repository, clock)
    _shutdown_started(repository)
    plug.on = False  # someone switched it off meanwhile
    plug.calls.clear()
    clock.advance(60)

    service.tick_power_plug(clock.now)

    assert plug.calls == []
    off = repository.list_workers().workers[0].power_events[0]
    assert off.kind.value == "plug_off"
    assert off.detail["already_off"] is True
    assert repository.plug_turned_on_at() is None


def test_the_ownership_marker_survives_an_agent_restart(
    tmp_path: Path, clock: Clock
) -> None:
    first = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    first.set_plug_turned_on_at(clock.now)
    first.close()

    second = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    try:
        assert second.plug_turned_on_at() == clock.now
        second.set_plug_turned_on_at(None)
        assert second.plug_turned_on_at() is None
    finally:
        second.close()


def test_the_wake_policy_reports_the_plug(
    tmp_path: Path, repository: DistributedJobRepository
) -> None:
    service, controller = _build(tmp_path, repository, FakePlug(), [])
    repository.register_worker(REGISTRATION)

    policy = service.read_wake_on_lan()

    assert policy["power_plug"] == {"enabled": True, **controller.describe()}


# -- Home Assistant -------------------------------------------------------------


class _Response:
    def __init__(self, body: object) -> None:
        self._raw = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _plug(opener: Any, **options: Any) -> HomeAssistantPlug:
    return HomeAssistantPlug(
        url="http://192.168.1.20:8123/",
        token="secret-token",
        switch_entity_id="switch.shellyplugsg3_80b54e297538",
        opener=opener,
        **options,
    )


def test_home_assistant_plug_reads_and_commands_the_switch() -> None:
    requests: list[Any] = []

    def opener(request: Any, **_: Any) -> _Response:
        requests.append(request)
        if request.get_method() == "GET":
            return _Response({"state": "off"})
        return _Response([])

    plug = _plug(opener)

    assert plug.read() == PlugReading(is_on=False, power_watts=None)
    plug.turn_on()
    plug.turn_off()

    assert requests[0].full_url == (
        "http://192.168.1.20:8123/api/states/switch.shellyplugsg3_80b54e297538"
    )
    assert requests[0].get_header("Authorization") == "Bearer secret-token"
    assert (
        requests[1].full_url == "http://192.168.1.20:8123/api/services/switch/turn_on"
    )
    assert json.loads(requests[1].data) == {
        "entity_id": "switch.shellyplugsg3_80b54e297538"
    }
    assert requests[2].full_url.endswith("/api/services/switch/turn_off")


def test_home_assistant_plug_reads_the_measured_power() -> None:
    states = {
        "switch.shellyplugsg3_80b54e297538": "on",
        "sensor.shellyplugsg3_80b54e297538_power": "31.4",
    }

    def opener(request: Any, **_: Any) -> _Response:
        return _Response({"state": states[request.full_url.rsplit("/", 1)[1]]})

    plug = _plug(opener, power_entity_id="sensor.shellyplugsg3_80b54e297538_power")
    assert plug.read() == PlugReading(is_on=True, power_watts=31.4)

    states["sensor.shellyplugsg3_80b54e297538_power"] = "unavailable"
    # An unreadable sensor is "unknown", never "idle".
    assert plug.read() == PlugReading(is_on=True, power_watts=None)


@pytest.mark.parametrize(
    "failure",
    [
        HTTPError("http://x", 401, "Unauthorized", {}, None),
        URLError("timed out"),
        TimeoutError("slow"),
    ],
)
def test_home_assistant_failures_are_plug_errors_without_the_token(
    failure: Exception,
) -> None:
    def opener(request: Any, **_: Any) -> _Response:
        raise failure

    with pytest.raises(PowerPlugError) as error:
        _plug(opener).read()
    assert "secret-token" not in str(error.value)


def test_an_unavailable_switch_is_an_error_not_an_off_plug() -> None:
    plug = _plug(lambda request, **_: _Response({"state": "unavailable"}))

    with pytest.raises(PowerPlugError, match="unavailable"):
        plug.read()


# -- the plugin ------------------------------------------------------------------


def _plugin_config(**changes: Any) -> PowerPlugPluginConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "home_assistant_url": "http://192.168.1.20:8123/",
        "access_token": "secret-token",
        "switch_entity_id": SWITCH,
        "power_entity_id": "sensor.shellyplugsg3_80b54e297538_power",
    }
    values.update(changes)
    return PowerPlugPluginConfig.model_validate(values)


def test_an_enabled_plug_needs_its_address_token_and_switch() -> None:
    for missing in ("home_assistant_url", "access_token", "switch_entity_id"):
        with pytest.raises(ValueError, match="requires"):
            _plugin_config(**{missing: None})
    assert not PowerPlugPluginConfig().enabled
    # A disabled plug may stay empty, and blanks mean "not set".
    assert _plugin_config(enabled=False, access_token="  ").access_token is None
    assert _plugin_config().home_assistant_url == "http://192.168.1.20:8123"
    with pytest.raises(ValueError):
        _plugin_config(switch_entity_id="light.bubule")


def test_a_missing_file_means_a_disabled_plug(tmp_path: Path) -> None:
    assert PowerPlugConfigLoader().load(tmp_path / "power-plug.yaml") == (
        PowerPlugPluginConfig()
    )


def test_the_shipped_example_is_valid_and_disabled() -> None:
    example = Path(__file__).parents[1] / "config/plugins/power-plug.example.yaml"

    configuration = PowerPlugConfigLoader().load(example)

    assert configuration.enabled is False
    assert configuration.access_token is None


def test_the_plugin_policy_follows_its_configuration() -> None:
    plugin = PowerPlugPlugin(config=PowerPlugPluginConfig())
    assert plugin.policy() is None  # off: the controller does nothing

    plugin.reconfigure(_plugin_config(boot_delay_seconds=20, idle_watts=3.0))

    policy = plugin.policy()
    assert policy is not None
    assert (policy.boot_delay_seconds, policy.idle_watts) == (20, 3.0)
    plugin.reconfigure(_plugin_config(enabled=False, access_token=None))
    assert plugin.policy() is None
    with pytest.raises(PowerPlugError, match="disabled"):
        plugin.read()


def test_a_disabled_plugin_leaves_the_wake_exactly_as_before(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plugin = PowerPlugPlugin(config=PowerPlugPluginConfig())
    service, _ = _build(tmp_path, repository, FakePlug(), wakes)
    service.power_plug = PowerPlugController(plugin, repository, policy=plugin.policy)
    _queue_work(repository, clock)

    assert service._wake_compatible_worker("system.health")  # noqa: SLF001

    assert wakes == [MAC]
    assert _kinds(repository) == ["wake_sent"]
    assert "plug" not in repository.list_workers().workers[0].power_events[0].detail
    assert "power_plug" not in service.read_wake_on_lan()
    clock.advance(600)
    service.tick_power_plug(clock.now)  # nothing to read, nothing to cut


def test_an_edit_applies_to_the_running_controller(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    wakes: list[str] = []
    plug = FakePlug(on=False)
    plugin = PowerPlugPlugin(
        config=PowerPlugPluginConfig(), client_factory=lambda _config: plug
    )
    service, _ = _build(tmp_path, repository, plug, wakes)
    service.power_plug = PowerPlugController(plugin, repository, policy=plugin.policy)
    _queue_work(repository, clock)
    plugin.reconfigure(_plugin_config())  # saved in Vision, no restart

    assert service._wake_compatible_worker("system.health")  # noqa: SLF001

    assert plug.calls == ["on"]
    assert wakes == []


def test_the_self_test_reads_without_commanding() -> None:
    plug = FakePlug(on=True, watts=31.4)
    plugin = PowerPlugPlugin(config=_plugin_config(), client_factory=lambda _: plug)

    result = plugin.execute()

    assert result.success is True
    assert result.message == "Prise allumée, 31.4 W."
    assert plug.calls == []
    plug.failing.add("read")
    failed = plugin.execute()
    assert failed.success is False
    assert "illisible" in failed.message
    assert "secret-token" not in failed.message
    disabled = PowerPlugPlugin(config=PowerPlugPluginConfig()).execute()
    assert disabled.success is False


# -- administration: the token is stored in the plugin file, masked ----------------


class _Bus:
    def publish(self, event: object) -> None:
        del event


def _admin(tmp_path: Path, content: str | None = None):
    path = tmp_path / "power-plug.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    plugin = PowerPlugPlugin(config=PowerPlugConfigLoader().load(path))
    context = PluginContext(
        event_bus=_Bus(),
        scheduler=None,
        dispatcher=None,
        memory=None,
        capability_manager=None,
        configuration=object(),
        runtime=object(),
    )
    manager = PluginManager(context=context)
    manager.register(plugin)
    applied: list[PowerPlugPluginConfig] = []

    def apply(configuration: PowerPlugPluginConfig) -> None:
        applied.append(configuration)
        plugin.reconfigure(configuration)

    repository = PluginAdministrationRepository(
        plugin_manager=manager,
        scheduler=Scheduler(
            clock=FakeClock(current_time=datetime(2026, 11, 10, tzinfo=UTC))
        ),
        bindings=(
            PluginAdministrationBinding(
                identifier="power_plug",
                display_name="Prise connectée",
                capabilities=("power_plug.control",),
                configuration_path=path,
                configuration_model=PowerPlugPluginConfig,
                optional_configuration=True,
                apply_configuration=apply,
                test_plugin=plugin.execute,
            ),
        ),
    )
    return repository, plugin, path, applied


STORED = (
    "enabled: true\n"
    "home_assistant_url: http://192.168.1.20:8123\n"
    "access_token: kept-token\n"
    f"switch_entity_id: {SWITCH}\n"
)


def test_the_token_is_saved_in_the_file_and_never_read_back(tmp_path: Path) -> None:
    repository, plugin, path, applied = _admin(tmp_path)
    assert repository.read("power_plug").enabled is False

    state = repository.write(
        "power_plug",
        {
            "enabled": True,
            "configuration": {
                "home_assistant_url": "http://192.168.1.20:8123",
                "access_token": "secret-token",
                "switch_entity_id": SWITCH,
                "power_entity_id": None,
            },
        },
    )

    assert "secret-token" in path.read_text(encoding="utf-8")
    assert state.configuration["access_token"] is None
    assert state.configuration["access_token_configured"] is True
    assert "secret-token" not in state.model_dump_json()
    assert plugin.policy() is not None
    assert applied[-1].enabled


def test_saving_with_a_blank_token_keeps_the_stored_one(tmp_path: Path) -> None:
    repository, plugin, path, _ = _admin(tmp_path, STORED)

    state = repository.write(
        "power_plug",
        {
            "enabled": True,
            "configuration": {
                "home_assistant_url": "http://192.168.1.21:8123",
                "access_token": None,
                "access_token_configured": True,
                "switch_entity_id": SWITCH,
                "idle_watts": 4.0,
            },
        },
    )

    saved = path.read_text(encoding="utf-8")
    assert "access_token: kept-token" in saved
    assert "192.168.1.21" in saved
    assert plugin.config.idle_watts == 4.0
    assert state.configuration["access_token_configured"] is True


def test_enabling_without_a_token_is_refused_and_changes_nothing(
    tmp_path: Path,
) -> None:
    repository, plugin, path, _ = _admin(tmp_path)

    with pytest.raises(ValueError):
        repository.write(
            "power_plug",
            {
                "enabled": True,
                "configuration": {
                    "home_assistant_url": "http://192.168.1.20:8123",
                    "switch_entity_id": SWITCH,
                },
            },
        )

    assert not path.exists()
    assert plugin.policy() is None


def test_the_test_button_reads_the_plug(tmp_path: Path) -> None:
    repository, plugin, _, _ = _admin(tmp_path, STORED)
    plugin._client_factory = lambda _config: FakePlug(on=False, watts=0.4)  # noqa: SLF001

    result = repository.test("power_plug")

    assert result.success is True
    assert result.check == "power_plug.status"
    assert "éteinte" in result.message
