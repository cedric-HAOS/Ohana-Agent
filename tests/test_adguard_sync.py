"""Proof of sync failure detection, safe comparison and runtime publication."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import dns.exception
import httpx
import pytest
import yaml

from ohana_agent.configuration.adguard_sync import AdGuardSyncPluginConfig
from ohana_agent.configuration.builders.adguard_sync import (
    AdGuardSyncConfigurationBuilder,
)
from ohana_agent.configuration.builders.infrastructure_builder import (
    InfrastructureBuilder,
)
from ohana_agent.configuration.infrastructure import InfrastructureConfig, ServiceConfig
from ohana_agent.configuration.loaders.adguard_sync import AdGuardSyncConfigLoader
from ohana_agent.configuration.loaders.infrastructure_loader import InfrastructureLoader
from ohana_agent.infrastructure.enums import HealthStatus
from ohana_agent.plugins.adguard_sync.config import AdGuardSyncConfig
from ohana_agent.plugins.adguard_sync.plugin import AdGuardSyncPlugin
from ohana_agent.plugins.adguard_sync.snapshot import AdGuardSnapshotProbe
from ohana_agent.plugins.adguard_sync.systemd import SystemdSyncProbe
from ohana_agent.runtime.bootstrap import build_production_agent
from ohana_agent.runtime.plugin_catalog import build_adguard_sync_tasks


def settings_file(tmp_path: Path, features=None) -> AdGuardSyncPluginConfig:
    path = tmp_path / "sync.yaml"
    document = {
        "origin": {
            "url": "http://192.168.1.11",
            "username": "admin",
            "password": "secret-origin",
        },
        "replica": {
            "url": "http://192.168.1.12",
            "username": "admin",
            "password": "secret-replica",
        },
        "features": {"dhcp": {"serverConfig": False, "staticLeases": False}},
    }
    if features:
        document["features"].update(features)
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return AdGuardSyncPluginConfig(sync_config_path=path)


def responses():
    return {
        "rewrite/list": [{"domain": "infra-01.ohana.lan", "answer": "192.168.1.10"}],
        "rewrite/settings": {"enabled": True},
        "access/list": {
            "allowed_clients": [],
            "disallowed_clients": [],
            "blocked_hosts": [],
        },
        "dns_info": {
            "upstream_dns": ["1.1.1.1"],
            "default_local_ptr_upstreams": ["127.0.0.1"],
        },
        "filtering/status": {
            "enabled": True,
            "interval": 24,
            "filters": [
                {
                    "id": 1,
                    "url": "https://filters.test/list",
                    "name": "Block",
                    "enabled": True,
                    "rules_count": 100,
                    "last_updated": "today",
                }
            ],
            "whitelist_filters": [],
            "user_rules": [],
        },
        "clients": {
            "clients": [
                {"name": "laptop", "ids": ["192.168.1.40"], "use_global_settings": True}
            ],
            "auto_clients": [{"name": "local-runtime-client"}],
        },
        "blocked_services/get": {"ids": [], "schedule": {"time_zone": "Europe/Paris"}},
        "profile": {"name": "admin", "language": "fr", "theme": "auto"},
        "parental/status": {"enabled": False},
        "safebrowsing/status": {"enabled": True},
        "safesearch/status": {"enabled": True, "google": True},
        "querylog/config": {"enabled": True, "interval": 24},
        "stats/config": {"enabled": True, "interval": 24},
    }


def mock_api(monkeypatch, origin, replica, *, dns_ok=True):
    requests = []
    real_client = httpx.Client

    def handle(request):
        requests.append(request)
        assert request.method == "GET"
        data = origin if request.url.host == "192.168.1.11" else replica
        path = request.url.path.removeprefix("/control/")
        return httpx.Response(200, json=data[path])

    monkeypatch.setattr(
        "ohana_agent.plugins.adguard_sync.snapshot.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    dns_requests = []

    def resolve(resolver, name, record_type, **kwargs):
        dns_requests.append((resolver.nameservers, name, kwargs["lifetime"]))
        if not dns_ok:
            raise dns.exception.Timeout()
        return ["192.168.1.10"]

    monkeypatch.setattr("dns.resolver.Resolver.resolve", resolve)
    return requests, dns_requests


def test_comparison_ignores_local_fields_and_filter_download_counters(
    tmp_path, monkeypatch
):
    origin = responses()
    replica = deepcopy(origin)
    replica["dns_info"]["default_local_ptr_upstreams"] = ["192.168.1.1"]
    replica["filtering/status"]["filters"][0].update(
        id=987, rules_count=99, last_updated="yesterday"
    )
    replica["clients"]["auto_clients"] = []
    replica["profile"]["name"] = "another-user"
    requests, dns_requests = mock_api(monkeypatch, origin, replica)
    result = AdGuardSnapshotProbe().inspect(settings_file(tmp_path))
    assert result["different_sections"] == []
    assert dns_requests == []
    assert all(
        request.headers.get("authorization", "").startswith("Basic ")
        for request in requests
    )
    assert "secret" not in str(result)
    assert "filters.test" not in str(result)


@pytest.mark.parametrize(
    "section, mutate, expected",
    [
        (
            "rewrite/list",
            lambda data: data[0].update(answer="192.168.1.99"),
            "dns.rewrites",
        ),
        ("rewrite/list", lambda data: data[0].update(enabled=False), "dns.rewrites"),
        (
            "dns_info",
            lambda data: data.update(upstream_dns=["8.8.8.8"]),
            "dns.server_config",
        ),
        (
            "filtering/status",
            lambda data: data.update(user_rules=["||ads.test^"]),
            "filters.user_rules",
        ),
        (
            "clients",
            lambda data: data["clients"][0].update(use_global_settings=False),
            "clients",
        ),
    ],
)
def test_reports_real_configuration_drift(
    tmp_path, monkeypatch, section, mutate, expected
):
    origin = responses()
    replica = deepcopy(origin)
    mutate(replica[section])
    mock_api(monkeypatch, origin, replica)
    result = AdGuardSnapshotProbe().inspect(settings_file(tmp_path))
    assert result["different_sections"] == [expected]


def test_disabled_features_are_not_compared(tmp_path, monkeypatch):
    origin = responses()
    replica = deepcopy(origin)
    replica["clients"]["clients"] = []
    replica["filtering/status"]["user_rules"] = ["secret-rule"]
    requests, _ = mock_api(monkeypatch, origin, replica)
    result = AdGuardSnapshotProbe().inspect(
        settings_file(tmp_path, {"clientSettings": False, "filters": False})
    )
    assert result["different_sections"] == []
    assert all(
        request.url.path not in {"/control/clients", "/control/filtering/status"}
        for request in requests
    )


@pytest.mark.parametrize("divergent", [False, True])
def test_dns_failure_does_not_affect_synchronization_health(
    tmp_path, monkeypatch, divergent
):
    replica = responses()
    if divergent:
        replica["clients"]["clients"] = []
    _, dns_requests = mock_api(monkeypatch, responses(), replica, dns_ok=False)
    result = AdGuardSyncPlugin(
        config=AdGuardSyncConfig(settings_file(tmp_path)), systemd=FakeCycle()
    ).execute()
    assert result.success == (not divergent)
    assert result.health == (
        HealthStatus.UNHEALTHY if divergent else HealthStatus.HEALTHY
    )
    assert result.metadata["sync_state"] == ("divergent" if divergent else "healthy")
    assert dns_requests == []
    assert "dns_checks" not in result.metadata
    assert "dns_healthy" not in result.metadata


@pytest.mark.parametrize("mode", ["unauthorized", "timeout", "malformed", "oversized"])
def test_api_failures_export_unknown_without_response_or_credentials(
    tmp_path, monkeypatch, mode
):
    real_client = httpx.Client

    def handle(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("secret-origin credentials", request=request)
        if mode == "unauthorized":
            return httpx.Response(401, text="secret-origin credentials")
        if mode == "oversized":
            return httpx.Response(200, content=b"x" * 2_000_001)
        return httpx.Response(200, json={"enabled": "secret-origin"})

    monkeypatch.setattr(
        "ohana_agent.plugins.adguard_sync.snapshot.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    result = AdGuardSyncPlugin(
        config=AdGuardSyncConfig(settings_file(tmp_path)), systemd=FakeCycle()
    ).execute(service_id="adguard-sync", node_id="infra-01")
    assert result.health == HealthStatus.UNKNOWN
    assert result.metadata["sync_state"] == "unverifiable"
    assert "secret-origin" not in str(result)
    assert not result.success


def test_dns_settings_match_replication_normalization(tmp_path, monkeypatch):
    origin = responses()
    origin["dns_info"].update(
        upstream_dns=["1.1.1.1", "8.8.8.8"],
        use_private_ptr_resolvers=True,
        local_ptr_upstreams=[],
        edns_cs_use_custom=False,
        edns_cs_custom_ip="192.168.1.11",
    )
    replica = deepcopy(origin)
    replica["dns_info"].update(
        upstream_dns=["8.8.8.8", "1.1.1.1"],
        use_private_ptr_resolvers=False,
        edns_cs_custom_ip="192.168.1.12",
    )
    mock_api(monkeypatch, origin, replica)
    assert (
        AdGuardSnapshotProbe().inspect(settings_file(tmp_path))["different_sections"]
        == []
    )


@pytest.mark.parametrize(
    "replica_until, expected",
    [
        ("2026-10-25T21:36:24.56717795+01:00", []),
        ("2026-10-25T21:36:13.143497714+01:00", []),
        ("2026-10-25T21:41:13.143497714+01:00", ["dns.server_config"]),
        (None, ["dns.server_config"]),
        ("not-a-date", ["dns.server_config"]),
    ],
)
def test_protection_pause_end_is_compared_with_replication_tolerance(
    tmp_path, monkeypatch, replica_until, expected
):
    origin = responses()
    origin["dns_info"]["protection_disabled_until"] = (
        "2026-10-25T21:36:13.143497714+01:00"
    )
    replica = deepcopy(origin)
    replica["dns_info"]["protection_disabled_until"] = replica_until
    mock_api(monkeypatch, origin, replica)
    result = AdGuardSnapshotProbe().inspect(settings_file(tmp_path))
    assert result["different_sections"] == expected


@pytest.mark.parametrize(
    "change",
    [
        lambda document: document["features"]["dhcp"].update(serverConfig=True),
        lambda document: document["features"].update(tlsConfig=True),
        lambda document: document["replica"].update(features={"services": False}),
        lambda document: document["replica"].update(url=document["origin"]["url"]),
        lambda document: document["replica"].update(
            url="https://admin:secret@example.test"
        ),
    ],
)
def test_unsupported_or_invalid_configuration_cannot_report_healthy(tmp_path, change):
    settings = settings_file(tmp_path)
    document = yaml.safe_load(settings.sync_config_path.read_text(encoding="utf-8"))
    change(document)
    settings.sync_config_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError):
        AdGuardSnapshotProbe().inspect(settings)


class FakeCycle:
    def __init__(self, state="fresh"):
        self.state = state

    def inspect(self, **kwargs):
        return {"state": self.state, "last_completed_age_seconds": 60}


class FakeSnapshot:
    def __init__(self, *, differences=None, error=None):
        self.result = {
            "different_sections": differences or [],
            "checked_sections": ["dns.rewrites"],
        }
        self.error = error
        self.calls = 0

    def inspect(self, settings):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


@pytest.mark.parametrize(
    "cycle_state",
    [
        "units_missing",
        "timer_inactive",
        "cycle_failed",
        "never_completed",
        "stale",
        "running",
    ],
)
def test_cycle_faults_cannot_be_hidden_by_equal_configuration(cycle_state):
    snapshot = FakeSnapshot()
    plugin = AdGuardSyncPlugin(
        config=AdGuardSyncConfig(AdGuardSyncPluginConfig()),
        systemd=FakeCycle(cycle_state),
        snapshot=snapshot,
    )
    result = plugin.execute(service_id="adguard-sync", node_id="infra-01")
    assert not result.success
    assert result.metadata["sync_state"] == cycle_state
    assert snapshot.calls == 0
    assert result.health == (
        HealthStatus.UNKNOWN if cycle_state == "running" else HealthStatus.UNHEALTHY
    )


@pytest.mark.parametrize(
    "snapshot, state, health",
    [
        (FakeSnapshot(), "healthy", HealthStatus.HEALTHY),
        (
            FakeSnapshot(differences=["dns.rewrites"]),
            "divergent",
            HealthStatus.UNHEALTHY,
        ),
        (
            FakeSnapshot(error=ValueError("secret-origin http://credentials.test")),
            "unverifiable",
            HealthStatus.UNKNOWN,
        ),
    ],
)
def test_observations_distinguish_drift_and_missing_evidence(snapshot, state, health):
    plugin = AdGuardSyncPlugin(
        config=AdGuardSyncConfig(AdGuardSyncPluginConfig()),
        systemd=FakeCycle(),
        snapshot=snapshot,
    )
    result = plugin.execute(service_id="adguard-sync", node_id="infra-01")
    assert result.metadata["sync_state"] == state
    assert result.health == health
    assert result.success == (state == "healthy")
    assert result.check == "adguard_sync.status"
    assert "secret" not in str(result)


def test_cycle_starting_during_comparison_discards_snapshot():
    cycle = FakeCycle()
    snapshot = FakeSnapshot()

    def inspect(settings):
        cycle.state = "running"
        return snapshot.result

    snapshot.inspect = inspect
    result = AdGuardSyncPlugin(
        config=AdGuardSyncConfig(AdGuardSyncPluginConfig()),
        systemd=cycle,
        snapshot=snapshot,
    ).execute()
    assert result.metadata["sync_state"] == "running"
    assert "different_sections" not in result.metadata


@pytest.mark.parametrize(
    "updates, expected",
    [
        ({}, "fresh"),
        ({"Result": "exit-code", "ExecMainStatus": "1"}, "cycle_failed"),
        ({"ExecMainExitTimestampMonotonic": "0"}, "never_completed"),
        ({"ExecMainExitTimestampMonotonic": "1000000"}, "stale"),
        (
            {
                "ActiveState": "activating",
                "ExecMainStartTimestampMonotonic": "990000000",
            },
            "running",
        ),
        (
            {"ActiveState": "activating", "ExecMainStartTimestampMonotonic": "1000000"},
            "stale",
        ),
    ],
)
def test_systemd_inspection_uses_exit_evidence_and_monotonic_age(
    monkeypatch, updates, expected
):
    monkeypatch.setattr(
        "ohana_agent.plugins.adguard_sync.systemd.monotonic", lambda: 1000
    )
    service = {
        "LoadState": "loaded",
        "ActiveState": "inactive",
        "Result": "success",
        "ExecMainStatus": "0",
        "ExecMainExitTimestampMonotonic": "940000000",
        **updates,
    }
    monkeypatch.setattr(
        SystemdSyncProbe,
        "_show",
        lambda self, unit: (
            {"LoadState": "loaded", "ActiveState": "active"}
            if unit.endswith("timer")
            else service
        ),
    )
    result = SystemdSyncProbe().inspect(maximum_age_seconds=900)
    assert result["state"] == expected


def test_systemctl_only_reads_fixed_units_with_bounded_timeout(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            stdout="LoadState=loaded\nActiveState=inactive\nResult=success\nExecMainStatus=0\nExecMainExitTimestampMonotonic=0\n"
        )

    monkeypatch.setattr("subprocess.run", run)
    assert (
        SystemdSyncProbe().inspect(maximum_age_seconds=900)["state"] == "timer_inactive"
    )
    assert all(
        command[:2] == ["systemctl", "show"] and options["timeout"] == 3
        for command, options in calls
    )


def test_absent_configuration_keeps_legacy_installation_disabled(tmp_path):
    assert not AdGuardSyncConfigLoader().load(tmp_path / "absent.yaml").enabled
    with pytest.raises(ValueError):
        AdGuardSyncPluginConfig(timeout=0)


def test_legacy_dns_probe_setting_is_ignored_without_relaxing_validation(tmp_path):
    path = tmp_path / "adguard-sync.yaml"
    path.write_text(
        "enabled: true\ndns_probe_name: infra-01.ohana.lan\n", encoding="utf-8"
    )
    config = AdGuardSyncConfigLoader().load(path)
    assert config.enabled
    assert "dns_probe_name" not in config.model_dump()
    with pytest.raises(ValueError):
        AdGuardSyncPluginConfig.model_validate({"unexpected_setting": True})


def test_shipped_example_is_valid_and_disabled():
    config = AdGuardSyncConfigLoader().load("config/plugins/adguard-sync.example.yaml")
    assert not config.enabled
    assert config.maximum_age_seconds == 900


def infrastructure_with_sync() -> InfrastructureConfig:
    config = InfrastructureLoader().load("config/infrastructure.yaml")
    return config.model_copy(
        update={
            "services": [
                *config.services,
                ServiceConfig(
                    id="adguard-sync",
                    name="Synchronisation AdGuard",
                    type="adguard_sync",
                    node="infra-01",
                ),
            ]
        }
    )


def test_service_binding_and_schedule_are_infrastructure_driven():
    infrastructure = InfrastructureBuilder().build(infrastructure_with_sync())
    config = AdGuardSyncConfigurationBuilder().build(
        infrastructure, AdGuardSyncPluginConfig(enabled=True)
    )
    (task,) = build_adguard_sync_tasks(config, 60, datetime.now(UTC))
    assert task.arguments == {"service_id": "adguard-sync", "node_id": "infra-01"}
    assert task.metadata["managed_by"] == "adguard_sync"
    with pytest.raises(ValueError):
        AdGuardSyncConfigurationBuilder().build(
            InfrastructureBuilder().build(
                InfrastructureLoader().load("config/infrastructure.yaml")
            ),
            AdGuardSyncPluginConfig(enabled=True),
        )


def test_production_dispatch_exports_sync_observation_and_supports_disable(
    tmp_path, monkeypatch
):
    from ohana_agent.observation.exporters import VisionInfrastructureMapper

    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(
        yaml.safe_dump(
            InfrastructureLoader()
            .load("config/infrastructure.yaml")
            .model_dump(mode="json")
        ),
        encoding="utf-8",
    )
    plugin_path = tmp_path / "adguard-sync.yaml"
    application_path = tmp_path / "shikamaru.yaml"
    token_path = tmp_path / "management.token"
    token_path.write_text("test-token\n", encoding="utf-8")
    application = yaml.safe_load(
        Path("config/shikamaru.yaml").read_text(encoding="utf-8")
    )
    application["administration"] = {
        "enabled": True,
        "token_file": token_path.as_posix(),
        "database_path": (tmp_path / "control.db").as_posix(),
        "dhcp": {"enabled": False},
    }
    application_path.write_text(yaml.safe_dump(application), encoding="utf-8")
    payloads = []
    vision = SimpleNamespace(
        send_observation=payloads.append, send_infrastructure=lambda payload: None
    )
    monkeypatch.setattr(
        SystemdSyncProbe, "inspect", lambda self, **kwargs: FakeCycle().inspect()
    )
    monkeypatch.setattr(
        AdGuardSnapshotProbe, "inspect", lambda self, settings: FakeSnapshot().result
    )
    agent = build_production_agent(
        application_config_path=application_path,
        infrastructure_config_path=infrastructure_path,
        adguard_sync_config_path=plugin_path,
        vision_client=vision,
    )
    repository = agent.administration_runtime.service.plugin_repository
    assert not plugin_path.exists()
    assert not repository.read("adguard_sync").enabled
    repository.write("adguard_sync", {"enabled": True, "configuration": {}})
    assert plugin_path.exists()
    tasks = [
        task
        for task in agent.scheduler.list_tasks()
        if task.command == "adguard_sync.status"
    ]
    assert len(tasks) == 1
    agent.scheduler.executor.dispatcher.execute(tasks[0].command, tasks[0].arguments)
    assert payloads[-1]["capability_id"] == "adguard_sync.status"
    assert payloads[-1]["service_id"] == "adguard-sync"
    assert payloads[-1]["node_id"] == "infra-01"
    assert payloads[-1]["status"] == "healthy"
    summary = agent.administration_runtime.service.read_companion_summary()
    tile = next(
        tile for tile in summary["services"]["items"] if tile["id"] == "adguard_sync"
    )
    assert tile["status"] == "healthy"
    assert tile["detail"] == "Dernière synchro il y a 1 min"
    assert any(
        service.type == "adguard_sync"
        for service in InfrastructureLoader().load(infrastructure_path).services
    )
    # Removing the infrastructure service also removes its scheduled observation.
    config = InfrastructureLoader().load("config/infrastructure.yaml")
    # Disable through the administration binding before removing the service.
    repository = agent.administration_runtime.service.plugin_repository
    assert repository.read("adguard_sync").task_count == 1
    assert repository.test("adguard_sync").success
    repository.write("adguard_sync", {"enabled": False, "configuration": {}})
    disabled_tile = next(
        tile
        for tile in agent.administration_runtime.service.read_companion_summary()[
            "services"
        ]["items"]
        if tile["id"] == "adguard_sync"
    )
    assert disabled_tile["status"] == "unknown"
    agent.apply_infrastructure_configuration(
        config, VisionInfrastructureMapper().to_payload(config)
    )
    assert not [
        task
        for task in agent.scheduler.list_tasks()
        if task.command == "adguard_sync.status"
    ]
    # Legacy installations expose the disabled plugin even without a YAML file.
    plugin_path.unlink()
    assert not repository.read("adguard_sync").enabled
    assert "adguard_sync" in {plugin.id for plugin in repository.list().plugins}
    # Failed first activation restores the absence of the optional file.
    with pytest.raises(ValueError):
        repository.write("adguard_sync", {"enabled": True, "configuration": {}})
    assert not plugin_path.exists()
    assert not repository.read("adguard_sync").enabled


@pytest.mark.parametrize(
    "path, field",
    [
        ("filtering/status", "filters"),
        ("filtering/status", "whitelist_filters"),
        ("filtering/status", "user_rules"),
        ("clients", "clients"),
    ],
)
def test_empty_api_lists_can_be_null(tmp_path, monkeypatch, path, field):
    origin = responses()
    replica = deepcopy(origin)
    origin[path][field] = None
    replica[path][field] = []
    mock_api(monkeypatch, origin, replica)
    result = AdGuardSnapshotProbe().inspect(settings_file(tmp_path))
    assert result["different_sections"] == []


@pytest.mark.parametrize(
    "path, field",
    [
        ("filtering/status", "filters"),
        ("filtering/status", "whitelist_filters"),
        ("filtering/status", "user_rules"),
        ("clients", "clients"),
    ],
)
@pytest.mark.parametrize("value", [False, {}, ""])
def test_malformed_api_lists_are_not_empty_lists(
    tmp_path, monkeypatch, path, field, value
):
    origin = responses()
    replica = deepcopy(origin)
    origin[path][field] = value
    mock_api(monkeypatch, origin, replica)
    with pytest.raises(ValueError):
        AdGuardSnapshotProbe().inspect(settings_file(tmp_path))


@pytest.mark.parametrize(
    "path, field",
    [
        ("filtering/status", "filters"),
        ("filtering/status", "whitelist_filters"),
        ("filtering/status", "user_rules"),
        ("clients", "clients"),
    ],
)
def test_missing_api_lists_are_not_empty_lists(tmp_path, monkeypatch, path, field):
    origin = responses()
    replica = deepcopy(origin)
    del origin[path][field]
    mock_api(monkeypatch, origin, replica)
    with pytest.raises(ValueError):
        AdGuardSnapshotProbe().inspect(settings_file(tmp_path))


def test_null_api_list_does_not_hide_replica_entries(tmp_path, monkeypatch):
    origin = responses()
    replica = deepcopy(origin)
    origin["clients"]["clients"] = None
    mock_api(monkeypatch, origin, replica)
    result = AdGuardSnapshotProbe().inspect(settings_file(tmp_path))
    assert result["different_sections"] == ["clients"]


def test_activation_validates_api_access_before_local_rewrites_exist(
    tmp_path, monkeypatch
):
    origin = responses()
    replica = deepcopy(origin)
    replica["clients"]["clients"] = None
    requests, dns_requests = mock_api(monkeypatch, origin, replica, dns_ok=False)
    AdGuardSnapshotProbe().validate_access(settings_file(tmp_path))
    assert {request.url.host for request in requests} == {
        "192.168.1.11",
        "192.168.1.12",
    }
    assert dns_requests == []


def test_inspection_reports_the_origin_protection_state(tmp_path, monkeypatch):
    origin = responses()
    origin["dns_info"].update(
        protection_enabled=False,
        protection_disabled_until="2026-10-25T21:36:13.143497714+01:00",
    )
    mock_api(monkeypatch, origin, deepcopy(origin))

    result = AdGuardSnapshotProbe().inspect(settings_file(tmp_path))

    assert result["protection"] == {
        "enabled": False,
        "disabled_until": "2026-10-25T21:36:13.143497714+01:00",
    }
    assert "secret" not in str(result)
