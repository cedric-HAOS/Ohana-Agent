"""An updated Agent provisions the service without losing operator settings."""

import sqlite3
from datetime import timedelta
from math import isfinite
from pathlib import Path

import pytest
import yaml

from ohana_agent.configuration.adguard_sync_service import ensure_adguard_sync_service
from ohana_agent.configuration.loaders.infrastructure_loader import InfrastructureLoader
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.companion_overview import services_overview
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.local_time import paris_now


def test_automatic_service_is_persisted_once_and_preserves_disabled_choice(tmp_path):
    path = tmp_path / "infrastructure.yaml"
    original = InfrastructureLoader().load("config/infrastructure.yaml")
    path.write_text(yaml.safe_dump(original.model_dump(mode="json")), encoding="utf-8")
    changed = ensure_adguard_sync_service(path, node_id="infra-01")
    assert changed.services[:-1] == original.services
    assert changed.nodes == original.nodes
    assert changed.topology == original.topology
    (tile,) = services_overview([], {"adguard-sync": "adguard_sync"})["items"]
    assert tile["status"] == "unknown"
    assert tile["label"] == "Synchro AdGuard"
    before = path.read_bytes()
    assert ensure_adguard_sync_service(path, node_id="infra-01") == changed
    assert path.read_bytes() == before
    payload = yaml.safe_load(before)
    payload["services"][-1]["enabled"] = False
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    assert (
        not ensure_adguard_sync_service(path, node_id="infra-01").services[-1].enabled
    )


def test_missing_local_node_does_not_create_a_dangling_service(tmp_path):
    path = tmp_path / "infrastructure.yaml"
    path.write_bytes(Path("config/infrastructure.yaml").read_bytes())
    before = path.read_bytes()
    ensure_adguard_sync_service(path, node_id="missing-local-node")
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "status, detail",
    [
        ("healthy", "Synchronisation vérifiée"),
        ("unhealthy", "Synchronisation en défaut"),
        ("unknown", "Synchronisation non vérifiée"),
    ],
)
def test_shizune_sync_tile_uses_the_real_observation_status(status, detail):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    overview = services_overview(
        [
            {
                "service": "adguard-sync",
                "capability": "adguard_sync.status",
                "status": status,
                "latency_ms": 20,
                "observed_at": datetime.now(ZoneInfo("Europe/Paris")),
            }
        ],
        {"adguard-sync": "adguard_sync"},
    )
    assert overview["items"][0]["detail"] == detail
    assert overview["checked_at"]


def test_old_success_is_not_a_current_sync_verification():
    from datetime import timedelta

    from ohana_agent.tsunade.local_time import paris_now

    (tile,) = services_overview(
        [
            {
                "service": "adguard-sync",
                "capability": "adguard_sync.status",
                "status": "healthy",
                "latency_ms": 20,
                "observed_at": paris_now() - timedelta(minutes=16),
            }
        ],
        {"adguard-sync": "adguard_sync"},
    )["items"]
    assert tile["status"] == "unknown"


@pytest.mark.parametrize(
    "age, detail",
    [
        (10, "Dernière synchro il y a moins d’une minute"),
        (135, "Dernière synchro il y a 3 min"),
        (3600, "Dernière synchro il y a 1 h"),
        (86400, "Dernière synchro il y a 1 j"),
        (None, "Synchronisation vérifiée"),
        (-1, "Synchronisation vérifiée"),
        (float("nan"), "Synchronisation vérifiée"),
    ],
)
def test_sync_age_accounts_for_time_since_observation(monkeypatch, age, detail):
    now = paris_now()
    monkeypatch.setattr("ohana_agent.tsunade.companion_overview.paris_now", lambda: now)
    (tile,) = services_overview(
        [
            {
                "service": "adguard-sync",
                "capability": "adguard_sync.status",
                "status": "healthy",
                "latency_ms": 20,
                "observed_at": now - timedelta(seconds=45),
                "last_sync_completed_at": (
                    now - timedelta(seconds=age + 45)
                    if age is not None and isfinite(age)
                    else None
                ),
            }
        ],
        {"adguard-sync": "adguard_sync"},
    )["items"]
    assert tile["detail"] == detail
    assert tile["status"] == "healthy"


def test_sync_cycle_age_survives_repository_restart(tmp_path, monkeypatch):
    now = paris_now()
    monkeypatch.setattr("ohana_agent.tsunade.companion_overview.paris_now", lambda: now)
    path = tmp_path / "control.db"
    repository = TsunadeIncidentRepository(path)
    repository.process(
        Observation(
            node="infra-01",
            service="adguard-sync",
            capability="adguard_sync.status",
            status=ObservationStatus.HEALTHY,
            success=True,
            message="verified",
            source="adguard_sync.status",
            timestamp=now - timedelta(seconds=45),
            metadata={"cycle": {"state": "fresh", "last_completed_age_seconds": 135}},
        )
    )
    repository._connection.close()
    reopened = TsunadeIncidentRepository(path)
    (tile,) = services_overview(
        reopened.capability_states(), {"adguard-sync": "adguard_sync"}
    )["items"]
    assert tile["detail"] == "Dernière synchro il y a 3 min"
    assert tile["status"] == "healthy"
    reopened._connection.close()


@pytest.mark.parametrize("status", ["unhealthy", "degraded", "unknown"])
def test_sync_fault_is_not_replaced_by_a_cycle_age(status):
    now = paris_now()
    (tile,) = services_overview(
        [
            {
                "service": "adguard-sync",
                "capability": "adguard_sync.status",
                "status": status,
                "latency_ms": 20,
                "observed_at": now,
                "last_sync_completed_at": now - timedelta(minutes=3),
            }
        ],
        {"adguard-sync": "adguard_sync"},
    )["items"]
    assert "Dernière synchro" not in tile["detail"]
    assert tile["status"] != "healthy"


def test_existing_capability_states_are_preserved_by_age_migration(tmp_path):
    path = tmp_path / "control.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE tsunade_capability_state (
            node_id TEXT, service_id TEXT, capability_id TEXT, status TEXT,
            observed_at TEXT, observation_id TEXT, latency_ms REAL,
            PRIMARY KEY(node_id,service_id,capability_id))""")
        connection.execute(
            "INSERT INTO tsunade_capability_state VALUES (?,?,?,?,?,?,?)",
            (
                "infra-01",
                "dns",
                "dns.resolve",
                "healthy",
                paris_now().isoformat(),
                "original",
                18.1,
            ),
        )
    for _ in range(2):
        repository = TsunadeIncidentRepository(path)
        (state,) = repository.capability_states()
        assert state["service"] == "dns"
        assert state["status"] == "healthy"
        assert state["latency_ms"] == 18.1
        assert state["last_sync_completed_at"] is None
        assert (
            repository._connection.execute(
                "SELECT observation_id FROM tsunade_capability_state"
            ).fetchone()[0]
            == "original"
        )
        repository._connection.close()
