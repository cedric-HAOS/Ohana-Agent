"""An updated Agent provisions the service without losing operator settings."""

from pathlib import Path

import pytest
import yaml

from ohana_agent.configuration.adguard_sync_service import ensure_adguard_sync_service
from ohana_agent.configuration.loaders.infrastructure_loader import InfrastructureLoader
from ohana_agent.tsunade.companion_overview import services_overview


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
