"""Phase 4 hardening: drifts tied only by a declared dependency between equipments."""

from __future__ import annotations

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.tsunade import preventive_rules
from ohana_agent.tsunade.incident_correlation import equipment_dependencies


def _infrastructure(declare: bool = True) -> InfrastructureConfig:
    zwave: dict[str, object] = {
        "id": "zwave",
        "name": "Z-Wave JS UI",
        "type": "zwave",
        "node": "zwave-01",
    }
    if declare:
        zwave["metadata"] = {"depends_on": ["mqtt"]}
    return InfrastructureConfig.model_validate(
        {
            "infrastructure": {"id": "konoha", "name": "Konoha"},
            "nodes": [
                {
                    "id": node,
                    "name": node,
                    "endpoint": {"type": "host", "address": f"{node}.ohana.lan"},
                }
                for node in ("ha-01", "zwave-01")
            ],
            "services": [
                {"id": "mqtt", "name": "Mosquitto", "type": "mqtt", "node": "ha-01"},
                zwave,
                {
                    "id": "mqtt-local",
                    "name": "Client local",
                    "type": "mqtt",
                    "node": "ha-01",
                    "metadata": {"depends_on": ["mqtt"]},
                },
            ],
        }
    )


def _drift(equipment: str, rule: str, title: str) -> dict:
    return {
        "equipment_id": equipment,
        "rule": rule,
        "title": title,
        "subject": equipment,
    }


def test_only_declarations_between_two_equipments_are_links() -> None:
    assert equipment_dependencies(_infrastructure()) == {
        "zwave-01": {"ha-01": ["Z-Wave JS UI dépend de Mosquitto"]}
    }
    assert equipment_dependencies(_infrastructure(declare=False)) == {}


def test_drifts_on_dependent_equipments_are_correlated_without_a_cause() -> None:
    dependencies = equipment_dependencies(_infrastructure())
    items = [
        _drift("zwave-01", "response_time", "ZWAVE-01 : réponse plus lente"),
        _drift("ha-01", "memory_growth", "HA-01 : mémoire en hausse"),
    ]

    [correlation] = preventive_rules.correlate_declared(items, dependencies)

    assert correlation["equipment_id"] == "zwave-01"
    assert correlation["upstream_equipment_id"] == "ha-01"
    assert correlation["declared"] == ["Z-Wave JS UI dépend de Mosquitto"]
    assert "ne prouve aucune cause" in correlation["note"]
    assert "HA-01 : mémoire en hausse" in items[0]["correlated_upstream"][0]
    assert "ZWAVE-01 : réponse plus lente" in items[1]["correlated_downstream"][0]


def test_simultaneous_drifts_without_a_declaration_stay_unrelated() -> None:
    items = [
        _drift("zwave-01", "response_time", "a"),
        _drift("ha-01", "memory_growth", "b"),
    ]

    assert preventive_rules.correlate_declared(items, {}) == []
    assert "correlated_upstream" not in items[0]


def test_a_downstream_drift_names_the_open_incident_of_its_upstream() -> None:
    dependencies = equipment_dependencies(_infrastructure())
    items = [_drift("zwave-01", "response_time", "ZWAVE-01 : réponse plus lente")]

    assert (
        preventive_rules.correlate_declared(
            items, dependencies, {"ha-01": ["mqtt.roundtrip"]}
        )
        == []
    )
    [text] = items[0]["upstream_incident"]
    assert text.startswith("mqtt.roundtrip sur ha-01")
    assert "Z-Wave JS UI dépend de Mosquitto" in text
