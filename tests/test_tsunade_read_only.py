"""Read-only probes execute bounded requests against configured endpoints only."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
import yaml

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.tsunade.read_only import diagnostic_snapshot, probe_endpoint


@pytest.mark.parametrize("node_id", ["infra-01", "zwave-01", "linky-01", "ha-01"])
@pytest.mark.parametrize("with_context", [True, False])
def test_snapshot_keeps_http_coverage_with_example_service_order(
    monkeypatch, node_id, with_context
):
    infrastructure = InfrastructureConfig.model_validate(
        yaml.safe_load(
            (
                Path(__file__).parents[1] / "config/infrastructure.example.yaml"
            ).read_text(encoding="utf-8")
        )
    )
    calls = []

    def probe(host, port, scheme):
        calls.append((host, port, scheme))
        return {"dns": "OK", "tcp": "OK"}

    monkeypatch.setattr("ohana_agent.tsunade.read_only.probe_endpoint", probe)
    result = diagnostic_snapshot(
        infrastructure,
        node_id,
        lambda: {},
        context_reader=(lambda: {}) if with_context else None,
    )
    assert ("192.168.1.20", 8123, "http") in calls
    assert len(calls) == (6 if with_context else 7)
    selected = [endpoint["target"] for endpoint in result["endpoints"]]
    requested = [
        service.id
        for service in infrastructure.services
        if service.enabled and service.node == node_id
    ]
    assert set(requested) <= set(selected)
    assert set(selected[: len(requested)]) == set(requested)
    omitted = result["omitted_targets"]
    assert len(omitted) == (2 if with_context else 1)
    assert all(item["reason"] == "probe_limit" for item in omitted)
    assert set(selected).isdisjoint(item["target"] for item in omitted)


@pytest.mark.parametrize("status", [302, 401, 403, 503])
def test_http_probe_uses_head_and_does_not_follow_redirects(status):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):  # noqa: N802
            calls.append((self.command, self.path))
            self.send_response(status)
            self.send_header("Location", "/modify")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = probe_endpoint("127.0.0.1", server.server_port, "http")
        assert result["tcp"] == "OK"
        assert result["http_status"] == status
        assert "http_error" not in result
        assert calls == [("HEAD", "/")]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("with_context", [True, False])
def test_snapshot_does_not_displace_requested_node_when_probe_budget_is_full(
    monkeypatch, with_context
):
    infrastructure = InfrastructureConfig.model_validate(
        {
            "infrastructure": {"id": "test", "name": "test"},
            "nodes": [
                {
                    "id": "local",
                    "name": "Local",
                    "endpoint": {"type": "hostname", "address": "local.test"},
                },
                {
                    "id": "ha",
                    "name": "HA",
                    "endpoint": {"type": "hostname", "address": "ha.test"},
                },
            ],
            "services": [
                {
                    "id": "http",
                    "name": "HTTP",
                    "type": "http",
                    "node": "ha",
                    "port": 80,
                },
                *[
                    {
                        "id": f"local-{index}",
                        "name": "Local",
                        "type": "mqtt",
                        "node": "local",
                        "port": 1800 + index,
                    }
                    for index in range(8)
                ],
            ],
        }
    )
    calls = []

    def probe(host, port, scheme):
        calls.append((host, port, scheme))
        return {"tcp": "OK"}

    monkeypatch.setattr("ohana_agent.tsunade.read_only.probe_endpoint", probe)
    result = diagnostic_snapshot(
        infrastructure,
        "local",
        lambda: {},
        context_reader=(lambda: {}) if with_context else None,
    )
    limit = 6 if with_context else 7
    assert len(calls) == limit
    assert {host for host, _, _ in calls} == {"local.test"}
    assert {item["target"] for item in result["omitted_targets"]} == {
        "http",
        *(f"local-{index}" for index in range(limit, 8)),
    }
    assert all(item["reason"] == "probe_limit" for item in result["omitted_targets"])


def test_snapshot_uses_declared_targets_and_labels_measurement_origin(monkeypatch):
    infrastructure = InfrastructureConfig.model_validate(
        {
            "infrastructure": {"id": "test", "name": "test"},
            "nodes": [
                {
                    "id": "ha",
                    "name": "HA",
                    "endpoint": {
                        "type": "http",
                        "address": "http://ha.local:8123/private?token=secret",
                    },
                },
                {
                    "id": "secret",
                    "name": "Secret",
                    "endpoint": {
                        "type": "http",
                        "address": "http://user:password@secret.local",
                    },
                },
            ],
            "services": [
                {"id": "ha", "name": "HA", "type": "http", "node": "ha", "port": 8123},
                {
                    "id": "mqtt",
                    "name": "MQTT",
                    "type": "mqtt",
                    "node": "ha",
                    "port": 1883,
                },
                {"id": "secret", "name": "Secret", "type": "http", "node": "secret"},
            ],
        }
    )
    calls = []

    def probe(host, port, scheme):
        calls.append((host, port, scheme))
        return {"tcp": "OK"}

    monkeypatch.setattr("ohana_agent.tsunade.read_only.probe_endpoint", probe)
    result = diagnostic_snapshot(infrastructure, "ha", lambda: {"cpu_percent": 12})
    assert set(calls) == {("ha.local", 8123, "http"), ("ha.local", 1883, None)}
    assert result["origin"]
    assert result["requested_node"] == "ha"
    assert result["host_metrics"]["cpu_percent"] == 12
    assert "secret" not in str(result)
    assert result["omitted_targets"] == []
    assert "pas depuis le nœud distant" in result["limits"]
