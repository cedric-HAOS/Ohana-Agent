import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

from observer import Observation, ObservationStatus
from observer.exporters import (
    HttpVisionClient,
    VisionObservationExporter,
    VisionObservationMapper,
)


class PipelineRequestHandler(BaseHTTPRequestHandler):
    """Capture an observation exported through HTTP."""

    payloads: list[dict[str, Any]] = []

    def do_POST(self) -> None:
        """Receive one observation."""
        content_length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )
        body = self.rfile.read(content_length)

        self.__class__.payloads.append(
            json.loads(body),
        )

        self.send_response(202)
        self.send_header(
            "Content-Type",
            "application/json",
        )
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(
        self,
        format: str,
        *args: object,
    ) -> None:
        """Disable server logs."""


@contextmanager
def run_pipeline_server() -> Iterator[str]:
    """Run the fake Vision ingestion endpoint."""
    PipelineRequestHandler.payloads = []

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        PipelineRequestHandler,
    )
    thread = Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    host, port = server.server_address

    try:
        yield f"http://{host}:{port}/api/observations"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_observation_is_mapped_and_sent_over_http() -> None:
    with run_pipeline_server() as observation_url:
        exporter = VisionObservationExporter(
            client=HttpVisionClient(
                observation_url=observation_url,
            ),
            mapper=VisionObservationMapper(),
        )
        observation = Observation(
            node="infra-01",
            service="dns-primary",
            capability="dns.resolve",
            status=ObservationStatus.HEALTHY,
            success=True,
            message="DNS resolution succeeded.",
            source="dns.resolve",
            latency_ms=12.5,
            metadata={
                "hostname": "example.com",
                "server": "192.168.1.10",
            },
        )

        exporter.export(observation)

    assert len(PipelineRequestHandler.payloads) == 1

    payload = PipelineRequestHandler.payloads[0]

    assert payload["node_id"] == "infra-01"
    assert payload["service_id"] == "dns-primary"
    assert payload["capability_id"] == "dns.resolve"
    assert payload["status"] == "healthy"
    assert payload["latency_ms"] == 12.5
    assert payload["metadata"]["hostname"] == "example.com"
    assert payload["metadata"]["agent_observation"] == {
        "id": str(observation.id),
        "source": "dns.resolve",
        "success": True,
        "message": "DNS resolution succeeded.",
    }


def test_suspended_observation_is_exported_as_unknown() -> None:
    with run_pipeline_server() as observation_url:
        exporter = VisionObservationExporter(
            client=HttpVisionClient(observation_url=observation_url),
            mapper=VisionObservationMapper(),
        )
        observation = Observation(
            node="sun-01",
            service="sun-01",
            capability="network.presence",
            status=ObservationStatus.SUSPENDED,
            success=True,
            message="Monitoring is outside its configured schedule.",
            source="network.presence",
            latency_ms=0.0,
            metadata={
                "monitoring_suspended": True,
                "next_activation": "2026-08-02T08:00:00+02:00",
            },
        )

        exporter.export(observation)

    assert len(PipelineRequestHandler.payloads) == 1
    payload = PipelineRequestHandler.payloads[0]
    assert payload["status"] == "unknown"
    assert payload["metadata"]["monitoring_suspended"] is True
    assert payload["metadata"]["next_activation"] == "2026-08-02T08:00:00+02:00"
