"""Tests for registered plugin administration."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from administration import (
    PluginAdministrationBinding,
    PluginAdministrationRepository,
)
from configuration.backup import BackupPluginConfig
from configuration.dns import DNSPluginConfig
from configuration.mqtt_plugin import MQTTPluginConfig
from observer import ObserverResult
from plugin.plugin_context import PluginContext
from plugin.plugin_manager import PluginManager
from plugins.backup.backup_plugin import BackupPlugin
from plugins.dns.dns_plugin import DNSPlugin
from plugins.mqtt.mqtt_plugin import MQTTPlugin
from scheduler import IntervalTrigger, Scheduler, Task
from scheduler.clock import FakeClock


class FakeEventBus:
    """Minimal event bus accepted by PluginManager."""

    def publish(self, event: object) -> None:
        del event


def make_repository(
    tmp_path: Path,
) -> tuple[
    PluginAdministrationRepository,
    list[DNSPluginConfig],
]:
    configuration_path = tmp_path / "dns.yaml"
    configuration_path.write_text(
        """\
enabled: true
queries:
  - example.com
timeout: 2.0
retries: 1
interval_seconds: 60
policy:
  minimum_healthy_servers: 1
""",
        encoding="utf-8",
    )
    context = PluginContext(
        event_bus=FakeEventBus(),
        scheduler=None,
        dispatcher=None,
        memory=None,
        capability_manager=None,
        configuration=object(),
        runtime=object(),
    )
    manager = PluginManager(context=context)
    manager.register(DNSPlugin())
    clock = FakeClock(current_time=datetime(2026, 7, 27, 10, 0, tzinfo=UTC))
    scheduler = Scheduler(clock=clock)
    scheduler.add_task(
        Task(
            id="dns.resolve:dns-primary:0:example.com",
            name="Resolve example.com",
            command="dns.resolve",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=60),
                start_at=clock.now(),
            ),
            metadata={"managed_by": "dns"},
        )
    )
    applied: list[DNSPluginConfig] = []
    repository = PluginAdministrationRepository(
        plugin_manager=manager,
        scheduler=scheduler,
        bindings=(
            PluginAdministrationBinding(
                identifier="dns",
                display_name="DNS",
                capabilities=("dns.resolve",),
                configuration_path=configuration_path,
                configuration_model=DNSPluginConfig,
                apply_configuration=applied.append,
                test_plugin=lambda: ObserverResult(
                    success=True,
                    latency=12.5,
                    check="dns.resolve",
                    message="DNS resolution succeeded.",
                    metadata={"hostname": "example.com"},
                ),
            ),
        ),
    )
    return repository, applied


def test_plugin_administration_lists_registered_plugins(
    tmp_path: Path,
) -> None:
    repository, _applied = make_repository(tmp_path)

    result = repository.list()

    assert len(result.plugins) == 1
    plugin = result.plugins[0]
    assert plugin.id == "dns"
    assert plugin.status == "active"
    assert plugin.enabled is True
    assert plugin.capabilities == ["dns.resolve"]
    assert plugin.interval_seconds == 60
    assert plugin.task_count == 1
    assert plugin.configuration["queries"] == ["example.com"]
    assert "enabled" not in plugin.configuration


def test_plugin_administration_persists_and_applies_configuration(
    tmp_path: Path,
) -> None:
    repository, applied = make_repository(tmp_path)

    updated = repository.write(
        "dns",
        {
            "enabled": False,
            "configuration": {
                "queries": ["ohana.lan"],
                "timeout": 3.5,
                "retries": 2,
                "interval_seconds": 120,
                "policy": {
                    "minimum_healthy_servers": 1,
                },
            },
        },
    )

    assert updated.enabled is False
    assert updated.status == "disabled"
    assert updated.interval_seconds == 120
    assert applied[-1].enabled is False
    assert applied[-1].queries == ["ohana.lan"]

    payload = yaml.safe_load((tmp_path / "dns.yaml").read_text(encoding="utf-8"))
    assert payload["enabled"] is False
    assert payload["interval_seconds"] == 120


def test_plugin_administration_executes_immediate_test(
    tmp_path: Path,
) -> None:
    repository, _applied = make_repository(tmp_path)

    result = repository.test("dns")

    assert result.plugin_id == "dns"
    assert result.success is True
    assert result.check == "dns.resolve"
    assert result.latency_ms == 12.5
    assert result.metadata["hostname"] == "example.com"


def test_plugin_administration_restores_configuration_when_apply_fails(
    tmp_path: Path,
) -> None:
    repository, applied = make_repository(tmp_path)

    def fail_once(configuration: DNSPluginConfig) -> None:
        applied.append(configuration)

        if configuration.interval_seconds == 120:
            raise RuntimeError("Unable to reconfigure DNS")

    repository.bindings["dns"] = PluginAdministrationBinding(
        identifier="dns",
        display_name="DNS",
        capabilities=("dns.resolve",),
        configuration_path=tmp_path / "dns.yaml",
        configuration_model=DNSPluginConfig,
        apply_configuration=fail_once,
        test_plugin=repository.bindings["dns"].test_plugin,
    )

    try:
        repository.write(
            "dns",
            {
                "enabled": True,
                "configuration": {
                    "queries": ["ohana.lan"],
                    "timeout": 3.5,
                    "retries": 2,
                    "interval_seconds": 120,
                    "policy": {
                        "minimum_healthy_servers": 1,
                    },
                },
            },
        )
    except RuntimeError as error:
        assert str(error) == "Unable to reconfigure DNS"
    else:
        raise AssertionError("The failing reconfiguration must be propagated")

    restored = yaml.safe_load((tmp_path / "dns.yaml").read_text(encoding="utf-8"))
    assert restored["interval_seconds"] == 60
    assert restored["queries"] == ["example.com"]
    assert applied[-1].interval_seconds == 60


def test_enabled_dns_plugin_rejects_an_empty_query_list(
    tmp_path: Path,
) -> None:
    repository, applied = make_repository(tmp_path)

    with pytest.raises(
        ValueError,
        match="must declare at least one query",
    ):
        repository.write(
            "dns",
            {
                "enabled": True,
                "configuration": {
                    "queries": [],
                    "timeout": 2.0,
                    "retries": 1,
                    "interval_seconds": 60,
                    "policy": {
                        "minimum_healthy_servers": 1,
                    },
                },
            },
        )

    assert applied == []
    persisted = yaml.safe_load((tmp_path / "dns.yaml").read_text(encoding="utf-8"))
    assert persisted["queries"] == ["example.com"]


def test_mqtt_password_is_masked_and_preserved_on_update(
    tmp_path: Path,
) -> None:
    configuration_path = tmp_path / "mqtt.yaml"
    configuration_path.write_text(
        """\
enabled: true
timeout: 5.0
retries: 1
interval_seconds: 60
keepalive_seconds: 60
client_id_prefix: ohana-agent
topic_prefix: ohana/agent/check
qos: 1
authentication:
  username: observer
  password: super-secret
tls:
  enabled: false
  ca_file: null
  insecure: false
""",
        encoding="utf-8",
    )
    context = PluginContext(
        event_bus=FakeEventBus(),
        scheduler=None,
        dispatcher=None,
        memory=None,
        capability_manager=None,
        configuration=object(),
        runtime=object(),
    )
    manager = PluginManager(context=context)
    manager.register(MQTTPlugin())
    applied: list[MQTTPluginConfig] = []
    repository = PluginAdministrationRepository(
        plugin_manager=manager,
        scheduler=Scheduler(),
        bindings=(
            PluginAdministrationBinding(
                identifier="mqtt",
                display_name="MQTT",
                capabilities=("mqtt.roundtrip",),
                configuration_path=configuration_path,
                configuration_model=MQTTPluginConfig,
                apply_configuration=applied.append,
                test_plugin=lambda: ObserverResult(
                    success=True,
                    latency=8.0,
                    check="mqtt.roundtrip",
                ),
            ),
        ),
    )

    current = repository.read("mqtt")
    authentication = current.configuration["authentication"]

    assert authentication["password"] is None
    assert authentication["password_configured"] is True
    assert current.configuration["home_assistant"]["enabled"] is True
    assert current.configuration["home_assistant"]["topic_prefix"] == "ohana"

    repository.write(
        "mqtt",
        {
            "enabled": True,
            "configuration": {
                **current.configuration,
                "interval_seconds": 120,
                "authentication": {
                    "username": "observer",
                    "password": None,
                },
            },
        },
    )

    assert applied[-1].authentication.password == "super-secret"
    persisted = yaml.safe_load(configuration_path.read_text(encoding="utf-8"))
    assert persisted["authentication"]["password"] == "super-secret"
    assert persisted["interval_seconds"] == 120


def test_backup_environment_secrets_are_reported_without_being_exposed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration_path = tmp_path / "backup.yaml"
    configuration_path.write_text(
        """\
enabled: false
rclone_remote: icloud:Ohana/Backups
targets:
  - id: ha-01
    label: HA-01
    enabled: true
    url: http://ha-01.ohana.lan:8123
    token_environment_variable: HA_TOKEN
    password_environment_variable: HA_PASSWORD
    schedule: 0 2 * * *
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HA_TOKEN", "secret-token")
    context = PluginContext(
        event_bus=FakeEventBus(),
        scheduler=None,
        dispatcher=None,
        memory=None,
        capability_manager=None,
        configuration=object(),
        runtime=object(),
    )
    manager = PluginManager(context=context)
    manager.register(BackupPlugin())
    applied: list[BackupPluginConfig] = []
    repository = PluginAdministrationRepository(
        plugin_manager=manager,
        scheduler=Scheduler(),
        bindings=(
            PluginAdministrationBinding(
                identifier="backup",
                display_name="Sauvegardes HAOS",
                capabilities=("backup.run",),
                configuration_path=configuration_path,
                configuration_model=BackupPluginConfig,
                apply_configuration=applied.append,
                test_plugin=lambda: ObserverResult(success=True),
            ),
        ),
    )

    current = repository.read("backup")
    target = current.configuration["targets"][0]
    assert target["token_configured"] is True
    assert target["password_configured"] is False
    assert "secret-token" not in str(current.configuration)

    current.configuration["targets"][0]["token"] = "new-home-assistant-token"
    current.configuration["targets"][0]["password"] = "new-encryption-password"

    updated = repository.write(
        "backup",
        {
            "enabled": True,
            "configuration": current.configuration,
        },
    )

    assert updated.enabled is True
    assert applied[-1].targets[0].url == "http://ha-01.ohana.lan:8123"
    assert applied[-1].targets[0].token == "new-home-assistant-token"
    assert applied[-1].targets[0].password == "new-encryption-password"
    assert updated.configuration["targets"][0]["token"] is None
    assert updated.configuration["targets"][0]["password"] is None
    assert updated.configuration["targets"][0]["token_configured"] is True
    assert updated.configuration["targets"][0]["password_configured"] is True
    persisted = yaml.safe_load(configuration_path.read_text(encoding="utf-8"))
    assert persisted["targets"][0]["token"] == "new-home-assistant-token"
    assert persisted["targets"][0]["password"] == "new-encryption-password"
    assert "token_configured" not in persisted["targets"][0]
    assert "password_configured" not in persisted["targets"][0]
