"""Read-only probes execute bounded requests against configured endpoints only."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.tsunade.read_only import diagnostic_snapshot, probe_endpoint


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
    assert "pas depuis le nœud distant" in result["limits"]
