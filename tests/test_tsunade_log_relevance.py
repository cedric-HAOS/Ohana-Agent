"""A service diagnosis keeps only the node's log anomalies about that service."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.investigations import InvestigationResult

STARTED = datetime(2026, 9, 25, 9, 11, tzinfo=UTC)
INFRASTRUCTURE = InfrastructureConfig.model_validate(
    {
        "infrastructure": {"id": "konoha", "name": "Konoha"},
        "nodes": [
            {
                "id": "ha-01",
                "name": "HA-01",
                "endpoint": {"type": "ip", "address": "192.168.1.20"},
            }
        ],
        "services": [
            {
                "id": "mqtt",
                "name": "MQTT",
                "type": "mqtt",
                "node": "ha-01",
                "implementation": "Mosquitto broker",
            }
        ],
    }
)


def _finding(signature: str) -> dict:
    return {
        "source": "ha-01",
        "signature": signature,
        "severity": "error",
        "category": "integration",
        "occurrences": 3,
        "trend": "new",
    }


class RefusedMqtt:
    infrastructure_reader = staticmethod(lambda: INFRASTRUCTURE)

    def execute(self, payload):
        return InvestigationResult(
            investigation_id=uuid4(),
            operation=payload["operation"],
            status="OK",
            started_at=STARTED,
            finished_at=STARTED,
            duration_seconds=0,
            result={"success": payload["operation"] != "mqtt.status"},
        )


def test_mqtt_diagnosis_drops_unrelated_ha_log_anomalies(tmp_path: Path) -> None:
    # Controlled failure #3: the MQTT diagnosis listed kasa and template
    # anomalies from HA-01's whole log review as if they explained the broker.
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        incident = repository.process(
            Observation(
                node="ha-01",
                service="mqtt",
                capability="mqtt.roundtrip",
                status=ObservationStatus.UNHEALTHY,
                success=False,
                message="[Errno 111] Connection refused",
                source="mqtt.roundtrip",
                id=uuid4(),
                timestamp=STARTED,
                metadata={"device_id": "ha-01"},
            )
        )
        service = TsunadeExpertiseService(
            incidents=repository,
            investigations=RefusedMqtt(),  # type: ignore[arg-type]
        )
        log_result = {
            "source": "ha-01",
            "findings": [
                _finding("kasa: Unable to connect to 192.168.1.44"),
                _finding("Template sensor.micro_inverter_roof_grid_current error"),
                _finding("Disconnected from MQTT server core-mosquitto:1883"),
            ],
        }

        outcome = service.diagnose(incident.incident_id, log_result=log_result)

        assert outcome.status == "DETERMINISTIC"
        facts = "\n".join(outcome.facts)
        assert "Disconnected from MQTT server" in facts
        assert "kasa" not in facts
        assert "micro_inverter" not in facts
        assert "2 anomalie(s) de journaux de HA-01 sans rapport avec mqtt" in facts
    finally:
        repository.close()
