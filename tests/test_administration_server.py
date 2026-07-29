"""Tests for the authenticated Agent administration API."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from administration import (
    AdministrationHTTPServer,
    AdministrationService,
    InfrastructureConfigurationRepository,
)

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
            agent_version="1.7.4",
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
    assert result["agent_version"] == "1.7.4"
    assert result["operations"] == [
        "infrastructure.read",
        "infrastructure.write",
    ]


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
    finally:
        server.stop()

    assert "plugins.read" in capabilities["operations"]
    assert "plugins.write" in capabilities["operations"]
    assert "plugins.test" in capabilities["operations"]
    assert plugins["plugins"][0]["id"] == "dns"  # type: ignore[index]
    assert plugin["id"] == "dns"
    assert updated["enabled"] is False
    assert tested["success"] is True
