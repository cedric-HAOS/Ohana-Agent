"""Phase 7: the companion summary shows essential services and logs by equipment."""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from ohana_agent.api.service import AdministrationService
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus
from ohana_agent.tsunade.companion_overview import (
    format_latency,
    logs_overview,
    services_overview,
)
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository

PARIS = ZoneInfo("Europe/Paris")
TYPES = {
    "dns-primary": "dns",
    "dns-secondary": "dns",
    "dhcp": "dhcp",
    "mqtt": "mqtt",
    "zwave": "zwave",
}
INFRASTRUCTURE = """\
infrastructure: {id: konoha, name: Konoha}
nodes:
  - {id: infra-01, name: INFRA-01, endpoint: {type: ip, address: 192.168.1.10}}
services:
  - {id: dns-primary, name: DNS, type: dns, node: infra-01, enabled: true}
  - {id: mqtt, name: MQTT, type: mqtt, node: infra-01, enabled: true}
"""


def _observation(
    service: str,
    capability: str,
    status: ObservationStatus = ObservationStatus.HEALTHY,
    *,
    latency_ms: float | None = None,
    at: datetime | None = None,
) -> Observation:
    return Observation(
        node="infra-01",
        service=service,
        capability=capability,
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message="m",
        source="test",
        timestamp=at or datetime.now(PARIS),
        latency_ms=latency_ms,
    )


def _log_result(source: str, findings: int) -> dict:
    return {
        "status": "KO" if findings else "OK",
        "analyzed_at": datetime.now(PARIS).isoformat(),
        "window_started_at": (datetime.now(PARIS) - timedelta(days=1)).isoformat(),
        "window_ended_at": datetime.now(PARIS).isoformat(),
        "sources": [
            {
                "source": source,
                "status": "OK",
                "findings": [
                    {
                        "signature": f"s{index}",
                        "severity": "error",
                        "occurrences": 1,
                        "message": "boom",
                    }
                    for index in range(findings)
                ],
            }
        ],
    }


def test_latency_is_short_and_french() -> None:
    assert format_latency(4.63) == "4,6 ms"
    assert format_latency(1234) == "1,2 s"


def test_service_tiles_follow_the_worst_check_and_only_configured_types(
    tmp_path: Path,
) -> None:
    incidents = TsunadeIncidentRepository(tmp_path / "control.db")
    for observation in (
        _observation("dns-primary", "dns.resolve", latency_ms=4.6),
        _observation("dns-secondary", "dns.resolve", ObservationStatus.DEGRADED),
        _observation("dhcp", "dhcp.status"),
        _observation("mqtt", "mqtt.roundtrip", latency_ms=12.3),
        _observation("zwave", "zwave.status", ObservationStatus.UNHEALTHY),
        # A device (network.reachable) is not an essential service.
        _observation("she-04", "network.reachable"),
    ):
        incidents.process(observation)

    overview = services_overview(incidents.capability_states(), TYPES)
    tiles = {tile["id"]: tile for tile in overview["items"]}

    assert list(tiles) == ["dns", "dhcp", "mqtt", "zwave"]
    # One degraded DNS makes the DNS tile degraded, however fast the other is.
    assert tiles["dns"]["status"] == "degraded"
    assert tiles["dns"]["detail"] == "Dégradé"
    assert tiles["dhcp"] == {
        "id": "dhcp",
        "label": "DHCP",
        "status": "healthy",
        "detail": "",
    }
    assert tiles["mqtt"]["detail"] == "12,3 ms"
    assert tiles["zwave"]["status"] == "critical"
    assert overview["checked_at"].endswith(("+01:00", "+02:00"))


def test_a_service_without_recent_measure_is_unknown_never_healthy(
    tmp_path: Path,
) -> None:
    incidents = TsunadeIncidentRepository(tmp_path / "control.db")
    incidents.process(
        _observation("dhcp", "dhcp.status", at=datetime.now(PARIS) - timedelta(days=5))
    )

    overview = services_overview(incidents.capability_states(), TYPES)
    dhcp = next(tile for tile in overview["items"] if tile["id"] == "dhcp")

    assert dhcp["status"] == "unknown"
    assert dhcp["detail"] == "Pas de mesure récente"
    assert overview["checked_at"] is None


def test_logs_by_equipment_show_decisions_noise_and_clean_sources(
    tmp_path: Path,
) -> None:
    incidents = TsunadeIncidentRepository(tmp_path / "control.db")
    incidents.record_log_health(uuid4(), _log_result("infra-01", 2))
    incidents.accept_log_signature("ha-01", "noise")
    active = incidents.list(state="active", limit=50)
    infra = next(item for item in active if item.equipment_id == "infra-01")

    waiting = logs_overview(
        active, {str(infra.incident_id)}, {"ha-01": 1}, datetime.now(PARIS)
    )
    rows = {row["equipment"]: row for row in waiting["equipments"]}

    assert [row["equipment"] for row in waiting["equipments"]] == [
        "infra-01",
        "ha-01",
        "linky-01",
        "zwave-01",
    ]
    assert rows["infra-01"]["status"] == "decision"
    assert rows["infra-01"]["detail"] == "2 anomalie(s) à examiner"
    assert rows["infra-01"]["incident_id"] == str(infra.incident_id)
    assert rows["ha-01"]["status"] == "watch"
    assert rows["ha-01"]["detail"] == "Bruit connu · 1 accepté(s)"
    assert rows["linky-01"] == {
        "equipment": "linky-01",
        "label": "LINKY-01",
        "incident_id": None,
        "status": "ok",
        "detail": "Aucune anomalie",
    }
    assert waiting["checked_at"].endswith(("+01:00", "+02:00"))

    undecided = logs_overview(active, set(), {}, None)
    assert undecided["checked_at"] is None
    assert {row["equipment"]: row["status"] for row in undecided["equipments"]}[
        "infra-01"
    ] == "attention"


def test_companion_summary_carries_services_and_logs(tmp_path: Path) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE, encoding="utf-8")
    incidents = TsunadeIncidentRepository(tmp_path / "control.db")
    incidents.process(_observation("dns-primary", "dns.resolve", latency_ms=4.6))
    incidents.process(_observation("mqtt", "mqtt.roundtrip"))
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        incident_repository=incidents,
    )

    summary = service.read_companion_summary()

    assert [
        (tile["label"], tile["status"], tile["detail"])
        for tile in summary["services"]["items"]
    ] == [("DNS", "healthy", "4,6 ms"), ("MQTT", "healthy", "")]
    assert [row["status"] for row in summary["logs"]["equipments"]] == ["ok"] * 4
    assert summary["logs"]["checked_at"] is None
    assert summary["konoha_state"] == "healthy"


def test_summary_survives_an_unreadable_infrastructure(tmp_path: Path) -> None:
    incidents = TsunadeIncidentRepository(tmp_path / "control.db")
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "missing.yaml"
        ),
        incident_repository=incidents,
    )

    summary = service.read_companion_summary()

    assert summary["services"] == {"checked_at": None, "items": []}
