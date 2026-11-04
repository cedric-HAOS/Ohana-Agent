"""Preventive rules on what ages quietly: updates, certificates, HA updates."""

import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ohana_agent.tsunade.local_time import to_paris
from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor
from ohana_agent.tsunade.preventive_expiry import (
    HA_NODE,
    HA_UPDATES_KIND,
    SYSTEM_KIND,
    SYSTEM_NODE,
    TLS_KIND,
    ExpirySampler,
    home_assistant_updates,
    probe_certificate,
    read_certificate_file,
)

NOW = to_paris(datetime(2026, 11, 20, 10, 0, tzinfo=UTC))


@pytest.fixture
def monitor(tmp_path: Path):
    instance = TsunadePreventiveMonitor(tmp_path / "preventive.db")
    yield instance
    instance.close()


def _days_ago(count: int) -> datetime:
    return NOW - timedelta(days=count)


def _system(monitor, days: int, **detail) -> None:
    """One snapshot per day for the last ``days`` days, today included."""
    for age in range(days):
        monitor.record_snapshot(
            SYSTEM_NODE,
            SYSTEM_KIND,
            _days_ago(age),
            {
                "security_count": 0,
                "pending_count": 0,
                "reboot_required": False,
                "lists_stale": False,
                "lists_age_days": 0.5,
                **detail,
            },
        )


def _check(monitor, rule: str) -> dict:
    summary = monitor.summary(now=NOW)
    return next(check for check in summary["checks"] if check["id"] == rule)


def _items(monitor, rule: str) -> list[dict]:
    return [item for item in monitor.summary(now=NOW)["watch"] if item["rule"] == rule]


def test_without_any_reading_the_rules_say_so_instead_of_reassuring(monitor):
    for rule in ("system_updates", "tls_certificates", "ha_updates"):
        assert _check(monitor, rule)["state"] == "insufficient_data"


def test_security_updates_are_watched_after_a_week_and_urgent_after_two(monitor):
    _system(monitor, 6, security_count=2, pending_count=3)
    assert _items(monitor, "system_updates") == []
    assert _check(monitor, "system_updates")["state"] == "ok"

    _system(monitor, 8, security_count=2, pending_count=3)
    (item,) = _items(monitor, "system_updates")
    assert item["subject"] == "security-updates"
    assert item["urgent"] is False
    assert "2 correctif(s) de sécurité en attente depuis 7 jours" in item["title"]

    _system(monitor, 15, security_count=2, pending_count=3)
    (item,) = _items(monitor, "system_updates")
    assert item["urgent"] is True


def test_installing_the_updates_restarts_the_clock(monitor):
    # Pending for 10 days, then installed 2 days ago: the run is only 2 days.
    for age in range(2, 12):
        monitor.record_snapshot(
            SYSTEM_NODE,
            SYSTEM_KIND,
            _days_ago(age),
            {"security_count": 2, "pending_count": 2, "lists_stale": False},
        )
    for age in range(0, 2):
        monitor.record_snapshot(
            SYSTEM_NODE,
            SYSTEM_KIND,
            _days_ago(age),
            {"security_count": 0, "pending_count": 0, "lists_stale": False},
        )

    assert _items(monitor, "system_updates") == []


def test_stale_package_lists_are_reported_at_once(monitor):
    _system(monitor, 1, lists_stale=True, lists_age_days=26.0)

    (item,) = _items(monitor, "system_updates")

    assert item["subject"] == "lists-stale"
    assert item["urgent"] is True
    assert "26 jours" in item["title"]


def test_a_pending_restart_is_watched_after_a_week(monitor):
    _system(monitor, 9, reboot_required=True)

    (item,) = _items(monitor, "system_updates")

    assert item["subject"] == "reboot-required"
    assert "depuis 8 jours" in item["title"]


def test_an_old_snapshot_is_no_evidence_of_today(monitor):
    for age in range(10, 20):
        monitor.record_snapshot(
            SYSTEM_NODE, SYSTEM_KIND, _days_ago(age), {"security_count": 5}
        )

    assert _check(monitor, "system_updates")["state"] == "insufficient_data"


def _certificates(monitor, **days_left: int) -> None:
    monitor.record_snapshot(
        SYSTEM_NODE,
        TLS_KIND,
        NOW,
        {
            "certificates": [
                {"label": label, "not_after": (NOW + timedelta(days=days)).isoformat()}
                for label, days in days_left.items()
            ]
        },
    )


def test_certificates_are_watched_under_thirty_days_and_urgent_under_seven(monitor):
    _certificates(monitor, Bank=400, Worker=20, CA=5)

    items = {item["subject"]: item for item in _items(monitor, "tls_certificates")}

    assert set(items) == {"certificate:Worker", "certificate:CA"}
    assert items["certificate:Worker"]["urgent"] is False
    assert items["certificate:CA"]["urgent"] is True
    assert "expirant dans 5 jours" in items["certificate:CA"]["title"]
    assert _check(monitor, "tls_certificates")["nodes"][0]["summary"].endswith(
        "5 jours"
    )


def test_an_expired_certificate_is_urgent(monitor):
    _certificates(monitor, Bank=-3)

    (item,) = _items(monitor, "tls_certificates")

    assert item["title"] == "Bank : certificat expiré"
    assert item["urgent"] is True


def _updates(monitor, days: int, *entities: str) -> None:
    for age in range(days):
        monitor.record_snapshot(
            HA_NODE,
            HA_UPDATES_KIND,
            _days_ago(age),
            {
                "count": len(entities),
                "updates": [
                    {
                        "entity_id": entity,
                        "title": "Mosquitto broker",
                        "installed_version": "6.5.0",
                        "latest_version": "6.5.2",
                    }
                    for entity in entities
                ],
            },
        )


def test_home_assistant_updates_are_watched_after_two_weeks(monitor):
    _updates(monitor, 10, "update.mosquitto_broker")
    assert _items(monitor, "ha_updates") == []

    _updates(monitor, 16, "update.mosquitto_broker")
    (item,) = _items(monitor, "ha_updates")

    assert item["subject"] == "update.mosquitto_broker"
    assert "Mosquitto broker à mettre à jour depuis 15 jours" in item["title"]
    assert "6.5.0 → 6.5.2" in item["detail"]


def test_only_update_entities_that_offer_an_update_are_kept():
    states = [
        {"entity_id": "update.core", "state": "on", "attributes": {"title": "Core"}},
        {"entity_id": "update.addon", "state": "off", "attributes": {}},
        {"entity_id": "sensor.x", "state": "on", "attributes": {}},
    ]

    assert [item["entity_id"] for item in home_assistant_updates(states)] == [
        "update.core"
    ]
    with pytest.raises(ValueError):
        home_assistant_updates({"not": "a list"})


def test_the_new_rules_can_be_muted(monitor):
    monitor.mute("system_updates", "security-updates", days=7, now=NOW)

    assert monitor.summary(now=NOW)["muted"] == []  # nothing to hide yet
    _system(monitor, 9, security_count=1)
    muted = monitor.summary(now=NOW)["muted"]
    assert [item["subject"] for item in muted] == ["security-updates"]
    with pytest.raises(ValueError):
        monitor.mute("unknown_rule", "x", days=7, now=NOW)


def _self_signed(path: Path, *, days: int, key_path: Path | None = None) -> datetime:
    key = ec.generate_private_key(ec.SECP256R1())
    if key_path is not None:
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    expires = datetime.now(UTC) + timedelta(days=days)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(expires)
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return expires


def test_a_certificate_file_is_read_for_its_expiry(tmp_path):
    expires = _self_signed(tmp_path / "worker.crt", days=40)

    read = read_certificate_file(tmp_path / "worker.crt")

    assert abs((read - expires).total_seconds()) < 2


def test_the_sampler_keeps_each_source_and_survives_a_failing_one():
    recorded: list[tuple[str, str, dict]] = []

    def failing():
        raise OSError("apt is busy")

    sampler = ExpirySampler(
        record_snapshot=lambda node, kind, _at, detail: recorded.append(
            (node, kind, detail)
        ),
        system_reader=failing,
        certificates=lambda: [
            ("Bank", lambda: NOW + timedelta(days=90)),
            ("Absent", failing),
        ],
        home_assistant_states=lambda: [
            {"entity_id": "update.core", "state": "on", "attributes": {}}
        ],
    )

    sampler.sample()

    kinds = [(node, kind) for node, kind, _detail in recorded]
    assert kinds == [(SYSTEM_NODE, TLS_KIND), (HA_NODE, HA_UPDATES_KIND)]
    certificates = recorded[0][2]["certificates"]
    assert [item["label"] for item in certificates] == ["Bank"]
    assert recorded[1][2]["count"] == 1


def test_a_tls_service_is_probed_for_the_certificate_it_presents(tmp_path):
    expires = _self_signed(
        tmp_path / "bank.crt", days=90, key_path=tmp_path / "bank.key"
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "bank.crt", tmp_path / "bank.key")
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def serve() -> None:
        connection, _address = server.accept()
        try:
            with context.wrap_socket(connection, server_side=True):
                pass
        except OSError:
            pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        read = probe_certificate("127.0.0.1", server.getsockname()[1], "bank.ohana.lan")
    finally:
        thread.join(timeout=5)
        server.close()

    # The certificate is untrusted (self-signed) and still gives its expiry.
    assert abs((read - expires).total_seconds()) < 2


def test_every_rule_of_the_summary_is_registered_and_can_be_muted(monitor):
    from ohana_agent.tsunade.preventive import all_rules

    registered = [rule["id"] for rule in all_rules()]
    evaluated = [check["id"] for check in monitor.summary(now=NOW)["checks"]]

    assert len(registered) == len(set(registered)), "a rule id is declared twice"
    assert set(evaluated) == set(registered), "summary and registry disagree"
    # Rules that used to be missing from the list: the owner may now set them aside.
    for rule in ("backup_restore", "icloud_session", "adguard_protection"):
        assert monitor.mute(rule, "any-subject", days=7, now=NOW)["rule"] == rule
