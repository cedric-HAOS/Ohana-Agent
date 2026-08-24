"""Tests for the authenticated Agent administration API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from administration import (
    AdministrationHTTPServer,
    AdministrationService,
    DistributedJobRepository,
    InfrastructureConfigurationRepository,
)
from administration.dhcp import DnsmasqDHCPRepository
from administration.expertise import TsunadeExpertiseConflictError
from administration.incidents import TsunadeIncidentRepository
from observer import Observation, ObservationStatus

INFRASTRUCTURE_YAML = """\
infrastructure:
  id: ohana-house
  name: Ohana House
  environment: production
nodes:
  - id: infra-01
    name: INFRA-01
    endpoint:
      type: ip
      address: 192.168.1.10
services:
  - id: dhcp-primary
    name: DHCP principal
    type: dhcp
    node: infra-01
    port: 67
topology:
  devices:
    - id: infra-01
      label: INFRA-01
      kind: raspberry_pi
      node: infra-01
"""


@pytest.fixture
def administration_server(
    tmp_path: Path,
) -> AdministrationHTTPServer:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(
        INFRASTRUCTURE_YAML,
        encoding="utf-8",
    )
    server = AdministrationHTTPServer(
        service=AdministrationService(
            infrastructure_repository=(
                InfrastructureConfigurationRepository(infrastructure_path)
            ),
            agent_version="1.8.1",
        ),
        token="test-secret",
        port=0,
    )
    server.start()

    yield server

    server.stop()


def request_json(
    server: AdministrationHTTPServer,
    path: str,
    *,
    token: str = "test-secret",
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """Call the temporary administration server."""
    assert server.address is not None
    host, port = server.address
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"http://{host}:{port}{path}",
        method=method,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )

    with urlopen(request, timeout=2) as response:
        result = json.load(response)

    assert isinstance(result, dict)
    return result


def test_administration_server_requires_token(
    administration_server: AdministrationHTTPServer,
) -> None:
    with pytest.raises(HTTPError) as error:
        request_json(
            administration_server,
            "/v1/capabilities",
            token="invalid",
        )

    assert error.value.code == 401


def test_administration_server_declares_available_operations(
    administration_server: AdministrationHTTPServer,
) -> None:
    result = request_json(
        administration_server,
        "/v1/capabilities",
    )

    assert result["schema_version"] == 1
    assert result["agent_version"] == "1.8.1"
    assert result["operations"] == [
        "infrastructure.read",
        "infrastructure.write",
    ]


def test_administration_server_exposes_authenticated_tsunade_incidents(
    tmp_path: Path,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    incidents = TsunadeIncidentRepository(tmp_path / "control.db")
    incident = incidents.process(
        Observation(
            node="infra-01",
            service="dns",
            capability="dns.resolve",
            status=ObservationStatus.DEGRADED,
            success=False,
            message="DNS degraded",
            source="dns.resolve",
            timestamp=datetime(2026, 8, 24, 12, tzinfo=UTC),
        )
    )
    assert incident is not None
    log_incident = incidents.process(
        Observation(
            node="ha-01",
            service="home-assistant",
            capability="logs.health",
            status=ObservationStatus.DEGRADED,
            success=False,
            message="Log anomaly detected",
            source="logs.health",
            timestamp=datetime(2026, 8, 24, 12, 5, tzinfo=UTC),
        )
    )
    assert log_incident is not None
    jobs = DistributedJobRepository(tmp_path / "jobs.db")
    reload_request = tmp_path / "run" / "dhcp-reload.request"
    dhcp = DnsmasqDHCPRepository(
        main_config_path=tmp_path / "dnsmasq.conf",
        reservation_paths={},
        leases_path=tmp_path / "leases",
        reload_request_path=reload_request,
    )

    class FakeExpertise:
        calls = 0

        def diagnose(self, incident_id):
            self.calls += 1
            if self.calls > 1:
                raise TsunadeExpertiseConflictError("expertise already queued")
            return {
                "incident_id": str(incident_id),
                "status": "AI_QUEUED",
                "known_procedure": False,
                "diagnosis": "Deterministic evidence is insufficient.",
                "facts": [],
                "proposals": [],
                "ai_job_id": "22222222-2222-4222-8222-222222222222",
            }

    server = AdministrationHTTPServer(
        service=AdministrationService(
            infrastructure_repository=InfrastructureConfigurationRepository(
                infrastructure_path
            ),
            dhcp_repository=dhcp,
            incident_repository=incidents,
            expertise_service=FakeExpertise(),  # type: ignore[arg-type]
            job_repository=jobs,
            log_sources=("ha-01", "linky-01", "zwave-01"),
        ),
        token="test-secret",
        port=0,
    )
    server.start()
    try:
        collection = request_json(server, "/v1/incidents")
        assert collection["summary"]["incident_count"] == 2  # type: ignore[index]
        assert collection["summary"]["log_control_count"] == 0  # type: ignore[index]
        assert collection["log_health"] is None
        assert str(incident.incident_id) in {
            item["incident_id"]
            for item in collection["incidents"]  # type: ignore[union-attr]
        }
        detailed = request_json(server, f"/v1/incidents/{incident.incident_id}")
        assert detailed["events"][0]["kind"] == "opened"  # type: ignore[index]
        recorded = request_json(
            server,
            f"/v1/incidents/{incident.incident_id}/records",
            method="POST",
            payload={"kind": "diagnostic", "summary": "Resolver unavailable"},
        )
        assert recorded["events"][-1]["kind"] == "diagnostic"  # type: ignore[index]
        diagnosis = request_json(
            server,
            f"/v1/incidents/{incident.incident_id}/diagnose",
            method="POST",
        )
        assert diagnosis["status"] == "AI_QUEUED"
        proposal = request_json(
            server,
            f"/v1/incidents/{incident.incident_id}/repairs",
            method="POST",
            payload={"operation": "restart_service"},
        )
        assert proposal["status"] == "proposed"
        assert not reload_request.exists()
        repair = request_json(
            server,
            f"/v1/incidents/{incident.incident_id}/repairs/authorize",
            method="POST",
            payload={
                "repair_id": proposal["repair_id"],
                "source": "vision",
                "authorized_by": "Cédric",
            },
        )
        assert repair["status"] == "verifying"
        assert repair["authorization_source"] == "vision"
        assert reload_request.exists()
        log_check = request_json(
            server,
            "/v1/incidents/logs/check",
            method="POST",
        )
        assert log_check["type"] == "logs.health_check"
        assert log_check["parameters"]["sources"] == [  # type: ignore[index]
            "ha-01",
            "linky-01",
            "zwave-01",
        ]
        collection_after_log_check = request_json(server, "/v1/incidents")
        assert (
            collection_after_log_check["summary"]["log_control_count"] == 1  # type: ignore[index]
        )
        assert collection_after_log_check["log_health"]["status"] == "QUEUED"  # type: ignore[index]
        with pytest.raises(HTTPError) as duplicate_log_check:
            request_json(server, "/v1/incidents/logs/check", method="POST")
        assert duplicate_log_check.value.code == 409
        log_investigation = request_json(
            server,
            f"/v1/incidents/{log_incident.incident_id}/logs/investigate",
            method="POST",
            payload={"pattern": "Node 17"},
        )
        assert log_investigation["type"] == "logs.investigate"
        assert log_investigation["parameters"]["source"] == "ha-01"  # type: ignore[index]
        assert log_investigation["parameters"]["pattern"] == "Node 17"  # type: ignore[index]
        with pytest.raises(HTTPError) as conflict:
            request_json(
                server,
                f"/v1/incidents/{incident.incident_id}/diagnose",
                method="POST",
            )
        assert conflict.value.code == 409
    finally:
        server.stop()
        jobs.close()
        incidents.close()


def test_administration_server_updates_infrastructure(
    administration_server: AdministrationHTTPServer,
) -> None:
    infrastructure = request_json(
        administration_server,
        "/v1/infrastructure",
    )
    infrastructure["services"].append(  # type: ignore[union-attr]
        {
            "id": "ntp-primary",
            "name": "NTP principal",
            "type": "ntp",
            "node": "infra-01",
            "port": 123,
        }
    )

    updated = request_json(
        administration_server,
        "/v1/infrastructure",
        method="PUT",
        payload=infrastructure,
    )

    assert len(updated["services"]) == 2  # type: ignore[arg-type]


def test_administration_service_publishes_saved_infrastructure(
    tmp_path: Path,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    changes = []
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        on_infrastructure_changed=changes.append,
    )
    payload = service.read_infrastructure().model_dump(mode="json")
    payload["services"].append(
        {
            "id": "dns-secondary",
            "name": "DNS secondaire",
            "type": "dns",
            "node": "infra-01",
            "port": 53,
        }
    )

    saved = service.write_infrastructure(payload)

    assert changes == [saved]
    assert changes[0].services[-1].id == "dns-secondary"


class FakePluginAdministrationRepository:
    """Return deterministic plugin administration documents."""

    def list(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plugins": [
                {
                    "id": "dns",
                    "name": "DNS",
                }
            ],
        }

    def read(self, identifier: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "id": identifier,
            "enabled": True,
        }

    def write(
        self,
        identifier: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "id": identifier,
            **payload,
        }

    def test(self, identifier: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plugin_id": identifier,
            "success": True,
        }

    def run_backup(self, target_id: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "target_id": target_id,
            "status": "accepted",
        }


def test_administration_server_exposes_plugin_routes(
    tmp_path: Path,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    server = AdministrationHTTPServer(
        service=AdministrationService(
            infrastructure_repository=(
                InfrastructureConfigurationRepository(infrastructure_path)
            ),
            plugin_repository=(
                FakePluginAdministrationRepository()  # type: ignore[arg-type]
            ),
        ),
        token="test-secret",
        port=0,
    )
    server.start()

    try:
        capabilities = request_json(server, "/v1/capabilities")
        plugins = request_json(server, "/v1/plugins")
        plugin = request_json(server, "/v1/plugins/dns")
        updated = request_json(
            server,
            "/v1/plugins/dns",
            method="PUT",
            payload={
                "enabled": False,
                "configuration": {},
            },
        )
        tested = request_json(
            server,
            "/v1/plugins/dns/test",
            method="POST",
        )
        backup_started = request_json(
            server,
            "/v1/plugins/backup/targets/ha-01/run",
            method="POST",
        )
    finally:
        server.stop()

    assert "plugins.read" in capabilities["operations"]
    assert "plugins.write" in capabilities["operations"]
    assert "plugins.test" in capabilities["operations"]
    assert "plugins.backup.run" in capabilities["operations"]
    assert plugins["plugins"][0]["id"] == "dns"  # type: ignore[index]
    assert plugin["id"] == "dns"
    assert updated["enabled"] is False
    assert tested["success"] is True
    assert backup_started["target_id"] == "ha-01"
    assert backup_started["status"] == "accepted"


class FakeNetworkRepository:
    """Expose deterministic host network changes."""

    def read(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "available": True,
            "interface": "eth0",
            "connection_name": "Wired connection 1",
            "method": "manual",
            "address": "192.168.1.10/24",
            "gateway": "192.168.1.1",
            "dns_servers": ["192.168.1.11"],
            "active": True,
            "state": "connected",
            "pending_change": None,
        }

    def apply(self, payload: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "transaction_id": "b" * 32,
            "expires_at": "2026-07-30T12:00:00Z",
            "state": self.read(),
        }

    def confirm(self, transaction_id: str) -> dict[str, object]:
        assert transaction_id == "b" * 32
        return self.read()

    def rollback(self, transaction_id: str) -> dict[str, object]:
        assert transaction_id == "b" * 32
        return self.read()


def test_administration_server_exposes_host_network_routes(tmp_path: Path) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    server = AdministrationHTTPServer(
        service=AdministrationService(
            infrastructure_repository=InfrastructureConfigurationRepository(
                infrastructure_path
            ),
            network_repository=FakeNetworkRepository(),  # type: ignore[arg-type]
        ),
        token="test-secret",
        port=0,
    )
    server.start()

    try:
        capabilities = request_json(server, "/v1/capabilities")
        state = request_json(server, "/v1/system/network")
        change = request_json(
            server,
            "/v1/system/network",
            method="PUT",
            payload={
                "schema_version": 1,
                "settings": {
                    "interface": "eth0",
                    "method": "manual",
                    "address": "192.168.1.10/24",
                    "gateway": "192.168.1.1",
                    "dns_servers": ["192.168.1.11"],
                },
            },
        )
        confirmed = request_json(
            server,
            f"/v1/system/network/{'b' * 32}/confirm",
            method="POST",
        )
        rolled_back = request_json(
            server,
            f"/v1/system/network/{'b' * 32}/rollback",
            method="POST",
        )
    finally:
        server.stop()

    assert "system.network.read" in capabilities["operations"]
    assert state["interface"] == "eth0"
    assert change["transaction_id"] == "b" * 32
    assert confirmed["active"] is True
    assert rolled_back["active"] is True
