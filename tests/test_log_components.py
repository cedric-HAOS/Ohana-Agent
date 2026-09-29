from __future__ import annotations

from uuid import uuid4

import pytest

from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.log_components import log_component

SIGNATURES = {
    "<timestamp> error (mainthread) [custom_components.tapo_control] "
    "httpsconnectionpool(host='<value>', port=<value>)": ("tapo_control", "Tapo"),
    "<timestamp> error (mainthread) [kasa.smart.smartdevice] error querying <value>": (
        "kasa",
        "Kasa",
    ),
    "<timestamp> error (mainthread) [aioshelly.rpc_device.wsrpc] invalid message": (
        "aioshelly",
        "Shelly",
    ),
    "<timestamp> error (mainthread) [homeassistant.components.shelly] error "
    "fetching shellyproem50-<value> data": ("shelly", "Shelly"),
    "<timestamp> error (mainthread) [homeassistant.components.template."
    "template_entity] templateerror": ("template", "Modèles Home Assistant"),
    "<timestamp> error (mainthread) [homeassistant.components.automation."
    "gestion_camera] gestion caméra: if at ste": (
        "automation.gestion_camera",
        "Automatisation Gestion Camera",
    ),
    "<timestamp> warning (paho-mqtt-client-<value>) [roombapy.roomba] "
    "unexpectedly disconnected": ("roombapy", "Roomba"),
    "<timestamp> infra-<value> ohana-agent[<value>]: <timestamp> warning "
    "ohana_agent.observation": ("ohana-agent", "Ohana Agent"),
    "<timestamp> warn teleinfo2mqtt: unable to publish frame": (
        "teleinfo2mqtt",
        "teleinfo2mqtt",
    ),
    "<timestamp> cntrlr [node <value>] timed out while waiting": (
        "zwave_js.controller",
        "Z-Wave JS (contrôleur)",
    ),
    "something without any logger name": ("other", "Autre"),
}


@pytest.mark.parametrize(("signature", "expected"), SIGNATURES.items())
def test_component_is_read_from_what_the_signature_contains(signature, expected):
    assert log_component({"signature": signature}) == expected


def _finding(signature: str, severity: str, occurrences: int) -> dict:
    return {
        "source": "ha-01",
        "signature": signature,
        "summary": signature,
        "severity": severity,
        "occurrences": occurrences,
    }


def _result(findings: list) -> dict:
    return {"sources": [{"source": "ha-01", "status": "KO", "findings": findings}]}


TAPO = "<timestamp> error (mainthread) [custom_components.tapo_control] timeout"
TAPO_OTHER = "<timestamp> error (mainthread) [custom_components.tapo_control] refused"
KASA = "<timestamp> error (mainthread) [kasa.smart.smartdevice] error querying"


def test_accepting_a_component_covers_its_variants_but_not_critical_lines(tmp_path):
    repository = TsunadeIncidentRepository(tmp_path / "incidents.db")
    try:
        incident_id = repository.record_log_health(
            uuid4(),
            _result(
                [
                    _finding(TAPO, "error", 84),
                    _finding(KASA, "error", 101),
                    _finding(
                        "<timestamp> critical (mainthread) [custom_components."
                        "tapo_control] fatal",
                        "critical",
                        1,
                    ),
                ]
            ),
        )[0]
        repository.accept_log_component("ha-01", "tapo_control", "Tapo")
        incident = repository.get(incident_id)
        assert incident.state == "active"
        assert sorted(item["component"] for item in incident.context["findings"]) == [
            "kasa",
            "tapo_control",
        ]
        assert [
            item["signature"] for item in incident.context["accepted_findings"]
        ] == [TAPO]

        repository.accept_log_component("ha-01", "kasa", "Kasa")
        incident = repository.get(incident_id)
        # A critical line of an accepted component still counts.
        assert incident.state == "active"
        assert [item["severity"] for item in incident.context["findings"]] == [
            "critical"
        ]
        assert {item["component"] for item in repository.accepted_log_components()} == {
            "tapo_control",
            "kasa",
        }
    finally:
        repository.close()


def test_new_variant_of_an_accepted_component_never_reopens(tmp_path):
    path = tmp_path / "incidents.db"
    repository = TsunadeIncidentRepository(path)
    try:
        incident_id = repository.record_log_health(
            uuid4(), _result([_finding(TAPO, "error", 84)])
        )[0]
        repository.accept_log_component("ha-01", "tapo_control", "Tapo")
        assert repository.get(incident_id).state == "resolved"
    finally:
        repository.close()

    repository = TsunadeIncidentRepository(path)
    try:
        # Tapo's error text keeps changing: the next review has a new variant.
        assert (
            repository.record_log_health(
                uuid4(), _result([_finding(TAPO_OTHER, "error", 17)])
            )
            == []
        )
        assert repository.revoke_log_component("ha-01", "tapo_control") is True
        assert repository.record_log_health(
            uuid4(), _result([_finding(TAPO_OTHER, "error", 17)])
        )
    finally:
        repository.close()


def test_overview_names_each_component_with_its_worst_severity(tmp_path):
    repository = TsunadeIncidentRepository(tmp_path / "incidents.db")
    try:
        result = _result(
            [
                _finding(TAPO, "error", 84),
                _finding(TAPO_OTHER, "warning", 17),
                _finding(KASA, "warning", 5),
            ]
        )
        repository.accept_log_component("ha-01", "kasa", "Kasa")
        [source] = repository.log_component_overview(result)
        assert source["source"] == "ha-01"
        tapo, kasa = source["components"]
        assert (tapo["label"], tapo["signatures"], tapo["occurrences"]) == (
            "Tapo",
            2,
            101,
        )
        assert tapo["severity"] == "error"
        assert tapo["accepted"] is False
        assert (kasa["label"], kasa["accepted"]) == ("Kasa", True)
    finally:
        repository.close()
