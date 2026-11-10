"""Security and lifecycle tests for the Shizune companion contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ohana_agent.api.http import AdministrationHTTPServer
from ohana_agent.api.service import AdministrationService
from ohana_agent.companions.notifications import APNsNotificationPublisher
from ohana_agent.companions.repository import CompanionRepository
from ohana_agent.configuration.administration import APNsConfig
from ohana_agent.host.dhcp import DnsmasqDHCPRepository
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.incidents import (
    TsunadeIncidentRepository,
)


def test_companion_diagnosis_is_authenticated_bounded_and_operator_requested(tmp_path):
    companions = CompanionRepository(tmp_path / "control.db")
    token = _pair(companions)
    incidents = TsunadeIncidentRepository(tmp_path / "control.db")
    incident = incidents.process(
        Observation(
            node="infra-01",
            service="dnsmasq",
            capability="dns.resolve",
            status=ObservationStatus.DEGRADED,
            success=False,
            message="DNS dégradé",
            source="dns.resolve",
            timestamp=datetime.now(UTC),
        )
    )
    calls = []

    class Expertise:
        def diagnose(self, incident_id, *, operator_requested):
            calls.append((incident_id, operator_requested))
            return SimpleNamespace(status="DETERMINISTIC")

    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infra.yaml"
        ),
        incident_repository=incidents,
        companion_repository=companions,
        expertise_service=Expertise(),
    )
    server = AdministrationHTTPServer(
        service=service, token="admin-test", companion_only=True, port=0
    )
    server.start()
    try:
        path = f"/v1/incidents/{incident.incident_id}/diagnose"
        with pytest.raises(HTTPError) as unauthenticated:
            _companion_request(server, path, method="POST", payload={})
        assert unauthenticated.value.code == 401
        with pytest.raises(HTTPError) as arbitrary:
            _companion_request(
                server,
                path,
                method="POST",
                payload={"command": "anything"},
                device_id="iphone-cedric",
                token=token,
            )
        assert arbitrary.value.code == 400
        assert not calls
        result = _companion_request(
            server,
            path,
            method="POST",
            payload={},
            device_id="iphone-cedric",
            token=token,
        )
        assert result == {"schema_version": 1, "status": "DETERMINISTIC"}
        assert calls == [(str(incident.incident_id), True)]
    finally:
        server.stop()
        incidents.close()
        companions.close()


INFRASTRUCTURE = """\
infrastructure:
  id: ohana-house
  name: Konoha
  environment: production
nodes:
  - id: infra-01
    name: INFRA-01
    endpoint: {type: ip, address: 192.168.1.10}
services:
  - {id: dnsmasq, name: DHCP, type: dhcp, node: infra-01, implementation: dnsmasq}
"""


def _companion_request(
    server: AdministrationHTTPServer,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    device_id: str | None = None,
    token: str | None = None,
) -> dict[str, object]:
    assert server.address is not None
    host, port = server.address
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if device_id is not None:
        headers["X-Ohana-Companion-Id"] = device_id
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"http://{host}:{port}{path}", method=method, data=data, headers=headers
    )
    with urlopen(request, timeout=2) as response:
        document = json.load(response)
    assert isinstance(document, dict)
    return document


def _pair(repository: CompanionRepository, device_id: str = "iphone-cedric") -> str:
    created = repository.create_pairing(
        {
            "protocol_version": 1,
            "device_id": device_id,
            "device_name": "iPhone de Cédric",
            "platform": "ios",
            "app_version": "0.1.0",
        },
        tls_ca_sha256="a" * 64,
        tls_ca_certificate_pem="-----BEGIN CERTIFICATE-----\n"
        + "A" * 64
        + "\n-----END CERTIFICATE-----",
    )
    repository.approve_pairing(created.pairing_id)
    result = repository.poll_pairing(
        created.pairing_id,
        {"protocol_version": 1, "polling_secret": created.polling_secret},
    )
    assert result.companion_token is not None
    return result.companion_token


def test_companion_pairing_token_expiry_push_and_revocation(tmp_path: Path) -> None:
    current = datetime(2026, 8, 24, 12, tzinfo=UTC)
    repository = CompanionRepository(
        tmp_path / "control.db",
        credential_ttl_days=1,
        utc_now=lambda: current,
    )
    token = _pair(repository)

    assert repository.authorize("iphone-cedric", token)
    assert repository.list_pairings().pairings[0].tls_ca_sha256 == "a" * 64
    registration = repository.register_push_token(
        "iphone-cedric",
        {
            "enabled": True,
            "device_token": "ab" * 32,
            "environment": "production",
        },
    )
    assert registration["enabled"] is True
    assert repository.push_targets("production") == [("iphone-cedric", "ab" * 32)]

    revoked = repository.revoke("iphone-cedric")
    assert revoked.revoked_at == current
    assert not repository.authorize("iphone-cedric", token)
    assert repository.push_targets("production") == []
    repository.close()


def test_companion_listener_exposes_only_synthetic_contract_and_executes_once(
    tmp_path: Path,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE, encoding="utf-8")
    control_path = tmp_path / "control.db"
    companions = CompanionRepository(control_path)
    token = _pair(companions)
    incidents = TsunadeIncidentRepository(control_path)
    incident = incidents.process(
        Observation(
            node="infra-01",
            service="dnsmasq",
            capability="dhcp.status",
            status=ObservationStatus.DEGRADED,
            success=False,
            message="dnsmasq est inactif.",
            source="dhcp.status",
            timestamp=datetime(2026, 8, 24, 12, tzinfo=UTC),
        )
    )
    assert incident is not None
    incidents.append_record(
        incident.incident_id,
        {
            "kind": "investigation",
            "summary": "dhcp.status : exécutée, résultat en échec",
            "payload": {
                "operation": "dhcp.status",
                "status": "OK",
                "result": {"success": False, "metadata": {"service_active": False}},
            },
        },
    )
    incidents.append_record(
        incident.incident_id,
        {
            "kind": "diagnostic",
            "summary": "Le service DHCP local échoue.",
            "payload": {"epistemic_status": "confirmed_by_probe"},
        },
    )
    reload_request = tmp_path / "run" / "dhcp-reload.request"
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        incident_repository=incidents,
        companion_repository=companions,
        companion_ca_sha256="a" * 64,
        companion_ca_certificate_pem=(
            "-----BEGIN CERTIFICATE-----\n" + "A" * 64 + "\n-----END CERTIFICATE-----"
        ),
        dhcp_repository=DnsmasqDHCPRepository(
            main_config_path=tmp_path / "dnsmasq.conf",
            reservation_paths={},
            leases_path=tmp_path / "leases",
            reload_request_path=reload_request,
        ),
    )
    repair = service.propose_incident_repair(
        str(incident.incident_id), {"operation": "restart_service"}
    )
    request_id = str(incidents.list_user_requests().requests[0].request_id)
    server = AdministrationHTTPServer(
        service=service,
        token="administration-secret",
        companion_only=True,
        port=0,
    )
    server.start()
    try:
        summary = _companion_request(
            server,
            "/v1/incidents/summary",
            device_id="iphone-cedric",
            token=token,
        )
        assert summary["konoha_state"] == "degraded"
        assert summary["pending_requests"] == 1
        requests = _companion_request(
            server,
            "/v1/incidents/requests",
            device_id="iphone-cedric",
            token=token,
        )
        assert requests["requests"][0]["choices"] == [  # type: ignore[index]
            "AUTHORIZE",
            "REFUSE",
            "LATER",
        ]
        assert "action_reference" not in requests["requests"][0]  # type: ignore[operator,index]
        with pytest.raises(HTTPError) as forbidden:
            _companion_request(
                server,
                "/v1/infrastructure",
                device_id="iphone-cedric",
                token=token,
            )
        assert forbidden.value.code == 404
        with pytest.raises(HTTPError) as hidden_suggestions:
            _companion_request(
                server,
                "/v1/incidents/suggestions",
                device_id="iphone-cedric",
                token=token,
            )
        assert hidden_suggestions.value.code == 404
        with pytest.raises(HTTPError) as unauthorized:
            _companion_request(server, "/v1/incidents/summary")
        assert unauthorized.value.code == 401

        answered = _companion_request(
            server,
            f"/v1/incidents/requests/{request_id}/response",
            method="POST",
            payload={"choice": "AUTHORIZE"},
            device_id="iphone-cedric",
            token=token,
        )
        assert answered["answer"] == "AUTHORIZE"
        assert answered["answer_source"] == "shizune"
        assert reload_request.exists()
        assert incidents.get_repair(repair.repair_id).status == "verifying"
        with pytest.raises(HTTPError) as duplicate:
            _companion_request(
                server,
                f"/v1/incidents/requests/{request_id}/response",
                method="POST",
                payload={"choice": "AUTHORIZE"},
                device_id="iphone-cedric",
                token=token,
            )
        assert duplicate.value.code == 422
    finally:
        server.stop()
        incidents.close()
        companions.close()


def test_apns_publisher_is_optional_deduplicated_and_independent_from_mqtt(
    tmp_path: Path,
) -> None:
    repository = CompanionRepository(tmp_path / "control.db")
    token = _pair(repository)
    assert repository.authorize("iphone-cedric", token)
    repository.register_push_token(
        "iphone-cedric",
        {
            "enabled": True,
            "device_token": "cd" * 32,
            "environment": "production",
        },
    )
    calls: list[tuple[str, str, str]] = []

    def send(device_id, device_token, notification, headers):
        assert headers["authorization"] == "bearer provider-token"
        calls.append((device_id, device_token, notification["type"]))
        return 200

    publisher = APNsNotificationPublisher(
        config=APNsConfig(
            enabled=True,
            environment="production",
            team_id="ABCDEFGHIJ",
            key_id="1234567890",
        ),
        companions=repository,
        request_sender=send,
        provider_token_factory=lambda: "provider-token",
    )
    notification = {
        "notification_id": "decision-1",
        "type": "DECISION_REQUIRED",
        "title": "Tsunade a besoin de vous",
        "message": "Autoriser la réparation ?",
    }
    publisher.publish(notification)
    publisher.publish(notification)

    assert publisher.wait_until_idle()
    assert calls == [("iphone-cedric", "cd" * 32, "DECISION_REQUIRED")]
    repository.close()


def test_expired_companion_session_is_refused(tmp_path: Path) -> None:
    current = datetime(2026, 8, 24, 12, tzinfo=UTC)
    repository = CompanionRepository(
        tmp_path / "control.db",
        credential_ttl_days=1,
        utc_now=lambda: current,
    )
    token = _pair(repository)
    assert repository.authorize("iphone-cedric", token)
    current += timedelta(days=2)
    assert not repository.authorize("iphone-cedric", token)
    repository.close()


def test_companion_reads_and_requests_the_system_update_through_fixed_routes(
    tmp_path,
):
    companions = CompanionRepository(tmp_path / "control.db")
    token = _pair(companions)
    requested = []

    class Requester:
        def status(self):
            return {"installed": True, "refresh": {"state": "never"}}

        def request(self, action):
            requested.append(action)
            return {"started": True, "busy": False, "action": action}

    state = {
        "status": "security_updates",
        "message": "2 correctifs de sécurité en attente",
        "pending_count": 5,
        "security_count": 2,
        "kernel_pending": False,
        "packages": [{"name": "openssl", "security": True}],
        "held_back": ["docker-ce"],
        "lists_refreshed_at": "2026-11-10T08:00:00+01:00",
        "lists_age_days": 0.1,
        "lists_stale": False,
        "reboot_required": False,
        "reboot_packages": [],
        "last_apt_run": {"command": "apt-get upgrade"},
        "read_at": "2026-11-10T10:00:00+01:00",
    }
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infra.yaml"
        ),
        companion_repository=companions,
        system_updates_reader=lambda: dict(state),
        system_update_requester=Requester(),
    )
    server = AdministrationHTTPServer(
        service=service, token="admin-test", companion_only=True, port=0
    )
    session = {"device_id": "iphone-cedric", "token": token}
    server.start()
    try:
        with pytest.raises(HTTPError) as anonymous:
            _companion_request(server, "/v1/system/updates")
        assert anonymous.value.code == 401

        updates = _companion_request(server, "/v1/system/updates", **session)
        assert updates["schema_version"] == 1
        assert updates["status"] == "security_updates"
        assert (updates["pending_count"], updates["security_count"]) == (5, 2)
        assert updates["helper"] == {"installed": True, "refresh": {"state": "never"}}
        # The package list and the apt history stay in Vision.
        assert not {"packages", "held_back", "reboot_packages", "last_apt_run"} & set(
            updates
        )

        with pytest.raises(HTTPError) as parameters:
            _companion_request(
                server,
                "/v1/system/updates/apply",
                method="POST",
                payload={"packages": ["openssl"]},
                **session,
            )
        assert parameters.value.code == 400
        with pytest.raises(HTTPError) as anonymous_request:
            _companion_request(
                server, "/v1/system/updates/apply", method="POST", payload={}
            )
        assert anonymous_request.value.code == 401
        assert requested == []

        refreshed = _companion_request(
            server, "/v1/system/updates/refresh", method="POST", payload={}, **session
        )
        applied = _companion_request(
            server, "/v1/system/updates/apply", method="POST", payload={}, **session
        )
        assert (refreshed["action"], applied["action"]) == ("refresh", "upgrade")
        assert requested == ["refresh", "upgrade"]

        # The same guards as from Vision, and no other system route.
        state.update(lists_stale=True)
        service._system_updates_cache = None
        with pytest.raises(HTTPError) as stale:
            _companion_request(
                server, "/v1/system/updates/apply", method="POST", payload={}, **session
            )
        assert stale.value.code == 422
        for path in ("/v1/system/network", "/v1/system/adguard-sync"):
            with pytest.raises(HTTPError) as hidden:
                _companion_request(server, path, **session)
            assert hidden.value.code == 404
        assert requested == ["refresh", "upgrade"]
    finally:
        server.stop()
