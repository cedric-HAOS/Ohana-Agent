"""Phase 4: things that expire or age quietly, reported before they hurt.

Three rules on facts that only get worse with time: the operating system's
security updates (and a package list too old to know of any), the local TLS
certificates, and the updates Home Assistant offers. A background sampler reads
each source every 30 minutes and keeps the day's latest reading with
``record_snapshot``; the rules only read those snapshots, so a summary never
waits for apt or a network probe. Nothing here opens an incident, installs an
update or renews a certificate.
"""

from __future__ import annotations

import json
import logging
import socket
import sqlite3
import ssl
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Any

from cryptography import x509

from ohana_agent.tsunade.local_time import paris_iso, paris_now, to_paris

LOGGER = logging.getLogger(__name__)

SYSTEM_NODE = "infra-01"
HA_NODE = "ha-01"
SYSTEM_KIND = "system_updates_snapshot"
TLS_KIND = "tls_certificates_snapshot"
HA_UPDATES_KIND = "ha_updates_snapshot"

SECURITY_WATCH_AFTER_DAYS = 7
SECURITY_URGENT_AFTER_DAYS = 14
REBOOT_WATCH_AFTER_DAYS = 7
STALE_LISTS_URGENT_DAYS = 14
CERTIFICATE_WATCH_DAYS = 30
CERTIFICATE_URGENT_DAYS = 7
HA_UPDATE_WATCH_AFTER_DAYS = 14
# A snapshot older than this says nothing about today: the sampler is failing.
FRESH_SNAPSHOT_DAYS = 2
SAMPLE_INTERVAL_SECONDS = 1800.0
FIRST_SAMPLE_DELAY_SECONDS = 120.0
MAX_UPDATES_KEPT = 50

RULES: tuple[dict[str, str], ...] = (
    {
        "id": "system_updates",
        "title": "Mises à jour du système",
        "rule": (
            f"Correctifs de sécurité apt en attente depuis plus de "
            f"{SECURITY_WATCH_AFTER_DAYS} jours (urgent au-delà de "
            f"{SECURITY_URGENT_AFTER_DAYS}), redémarrage requis depuis plus de "
            f"{REBOOT_WATCH_AFTER_DAYS} jours, ou listes de paquets périmées "
            "(plus de 3 jours : les mises à jour en attente sont alors "
            "inconnues). L'Agent ne met jamais le système à jour de lui-même."
        ),
    },
    {
        "id": "tls_certificates",
        "title": "Certificats TLS locaux",
        "rule": (
            f"Certificat d'un service local expirant sous {CERTIFICATE_WATCH_DAYS} "
            f"jours (urgent sous {CERTIFICATE_URGENT_DAYS} jours ou expiré) : "
            "Ohana-Bank, listeners de l'Agent et leur autorité locale."
        ),
    },
    {
        "id": "ha_updates",
        "title": "Mises à jour de Home Assistant",
        "rule": (
            f"Mise à jour proposée par Home Assistant (système, modules, "
            f"intégrations ou équipements) et restée sans suite depuis plus de "
            f"{HA_UPDATE_WATCH_AFTER_DAYS} jours."
        ),
    },
)


# Reading ---------------------------------------------------------------------


def certificate_not_after(certificate: x509.Certificate) -> datetime:
    return certificate.not_valid_after_utc


def read_certificate_file(path: Path) -> datetime:
    """Expiry of the first certificate of a PEM file."""
    return certificate_not_after(x509.load_pem_x509_certificate(path.read_bytes()))


def probe_certificate(
    host: str, port: int, server_name: str, *, timeout: float = 5.0
) -> datetime:
    """Expiry of the certificate a TLS service presents (no trust decision)."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=server_name) as secured:
            der = secured.getpeercert(binary_form=True)
    if not der:
        raise ValueError("the service presented no certificate")
    return certificate_not_after(x509.load_der_x509_certificate(der))


def home_assistant_updates(states: Any) -> list[dict[str, str]]:
    """The ``update.*`` entities that currently offer an update."""
    if not isinstance(states, list):
        raise ValueError("Home Assistant /api/states must return a list")
    updates = []
    for item in states:
        if not (
            isinstance(item, dict)
            and item.get("state") == "on"
            and str(item.get("entity_id", "")).startswith("update.")
        ):
            continue
        attributes = item.get("attributes") or {}
        updates.append(
            {
                "entity_id": str(item["entity_id"]),
                "title": str(
                    attributes.get("title") or attributes.get("friendly_name") or ""
                ),
                "installed_version": str(attributes.get("installed_version") or ""),
                "latest_version": str(attributes.get("latest_version") or ""),
            }
        )
    return sorted(updates, key=lambda update: update["entity_id"])[:MAX_UPDATES_KEPT]


class ExpirySampler:
    """Background reader; one failing source never stops the others."""

    def __init__(
        self,
        *,
        record_snapshot: Callable[[str, str, datetime, dict[str, Any]], None],
        system_reader: Callable[[], dict[str, Any]] | None = None,
        certificates: Callable[[], list[tuple[str, Callable[[], datetime]]]]
        | None = None,
        home_assistant_states: Callable[[], Any] | None = None,
        interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
        first_delay_seconds: float = FIRST_SAMPLE_DELAY_SECONDS,
        clock: Callable[[], datetime] = paris_now,
    ) -> None:
        self.clock = clock
        self.record_snapshot = record_snapshot
        self.system_reader = system_reader
        self.certificates = certificates
        self.home_assistant_states = home_assistant_states
        self.interval_seconds = interval_seconds
        self.first_delay_seconds = first_delay_seconds
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="ohana-expiry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def sample(self) -> None:
        now = self.clock()
        if self.system_reader is not None:
            try:
                state = self.system_reader()
                self.record_snapshot(
                    SYSTEM_NODE,
                    SYSTEM_KIND,
                    now,
                    {
                        key: state.get(key)
                        for key in (
                            "security_count",
                            "pending_count",
                            "reboot_required",
                            "lists_stale",
                            "lists_age_days",
                        )
                    },
                )
            except Exception as error:  # noqa: BLE001 - retried at the next sample.
                LOGGER.info("System update sample skipped: %s", error)
        if self.certificates is not None:
            readings: list[dict[str, Any]] = []
            for label, read in self.certificates():
                try:
                    readings.append({"label": label, "not_after": paris_iso(read())})
                except Exception as error:  # noqa: BLE001 - a service may be absent.
                    LOGGER.info("Certificate %s skipped: %s", label, error)
            if readings:
                self.record_snapshot(
                    SYSTEM_NODE, TLS_KIND, now, {"certificates": readings}
                )
        if self.home_assistant_states is not None:
            try:
                updates = home_assistant_updates(self.home_assistant_states())
                self.record_snapshot(
                    HA_NODE,
                    HA_UPDATES_KIND,
                    now,
                    {"count": len(updates), "updates": updates},
                )
            except Exception as error:  # noqa: BLE001 - retried at the next sample.
                LOGGER.info("Home Assistant update sample skipped: %s", error)

    def _run(self) -> None:
        if self._stop.wait(self.first_delay_seconds):
            return
        while True:
            self.sample()
            if self._stop.wait(self.interval_seconds):
                return


# Rules -----------------------------------------------------------------------


def _snapshots(
    connection: sqlite3.Connection, node: str, kind: str, current: datetime
) -> list[tuple[datetime, dict[str, Any]]]:
    """Daily snapshots, newest first, as (day at midnight Paris, detail)."""
    rows = connection.execute(
        """SELECT occurred_at, detail_json FROM tsunade_trend_events
        WHERE node_id = ? AND kind = ? ORDER BY occurred_at DESC""",
        (node, kind),
    ).fetchall()
    snapshots = []
    for row in rows:
        try:
            day = datetime.fromisoformat(row["occurred_at"]).replace(
                tzinfo=to_paris(current).tzinfo
            )
            snapshots.append((day, json.loads(row["detail_json"])))
        except (TypeError, ValueError):
            continue
    return snapshots


def _fresh(
    snapshots: list[tuple[datetime, dict[str, Any]]], current: datetime
) -> dict[str, Any] | None:
    if not snapshots:
        return None
    day, detail = snapshots[0]
    if to_paris(current) - day > timedelta(days=FRESH_SNAPSHOT_DAYS + 1):
        return None
    return detail


def _running_since(
    snapshots: list[tuple[datetime, dict[str, Any]]],
    holds: Callable[[dict[str, Any]], bool],
) -> datetime | None:
    """First day of the unbroken run of snapshots, up to now, where ``holds``."""
    since = None
    for day, detail in snapshots:
        if not holds(detail):
            break
        since = day
    return since


def _days(current: datetime, since: datetime) -> int:
    return max((to_paris(current) - since).days, 0)


def _rule(rule_id: str) -> dict[str, str]:
    return next(dict(rule) for rule in RULES if rule["id"] == rule_id)


def _check(
    rule_id: str,
    node_id: str,
    summary: str,
    items: list[dict[str, Any]],
    *,
    known: bool,
) -> dict[str, Any]:
    state = "watch" if items else "ok" if known else "insufficient_data"
    return {
        **_rule(rule_id),
        "state": state,
        "nodes": [
            {
                "node_id": node_id,
                "state": "watch" if items else "ok" if known else "insufficient_data",
                "summary": summary,
            }
        ],
        "items": items,
    }


def system_updates(connection: sqlite3.Connection, current: datetime) -> dict:
    snapshots = _snapshots(connection, SYSTEM_NODE, SYSTEM_KIND, current)
    latest = _fresh(snapshots, current)
    if latest is None:
        return _check(
            "system_updates",
            SYSTEM_NODE,
            "Mises à jour : pas de relevé récent",
            [],
            known=False,
        )
    items: list[dict[str, Any]] = []

    def item(
        subject: str,
        title: str,
        detail: str,
        since: datetime,
        urgent: bool,
        evidence: dict,
    ) -> None:
        items.append(
            {
                "rule": "system_updates",
                "node_id": SYSTEM_NODE,
                "equipment_id": SYSTEM_NODE,
                "subject": subject,
                "title": title,
                "detail": detail,
                "since": since.date().isoformat(),
                "urgent": urgent,
                "evidence": evidence,
            }
        )

    if latest.get("lists_stale"):
        age = latest.get("lists_age_days")
        age_text = f"{age:g} jours" if isinstance(age, int | float) else "longtemps"
        item(
            "lists-stale",
            f"INFRA-01 : listes de paquets périmées ({age_text})",
            "Les mises à jour en attente ne sont pas connues. Les listes se "
            "rafraîchissent chaque jour quand l'Installer a provisionné apt ; "
            "sinon, les actualiser depuis la page « Mise à jour système » de Vision.",
            snapshots[0][0],
            isinstance(age, int | float) and age > STALE_LISTS_URGENT_DAYS,
            {"lists_age_days": age},
        )
    security = _running_since(
        snapshots, lambda detail: bool(detail.get("security_count"))
    )
    if security is not None and _days(current, security) >= SECURITY_WATCH_AFTER_DAYS:
        count = latest.get("security_count") or 0
        days = _days(current, security)
        item(
            "security-updates",
            f"INFRA-01 : {count} correctif(s) de sécurité en attente "
            f"depuis {days} jours",
            "Installer depuis la page « Mise à jour système » de Vision ; un noyau "
            "ou une bibliothèque système demande ensuite un redémarrage.",
            security,
            days >= SECURITY_URGENT_AFTER_DAYS,
            {"security_count": count, "pending_count": latest.get("pending_count")},
        )
    reboot = _running_since(
        snapshots, lambda detail: bool(detail.get("reboot_required"))
    )
    if reboot is not None and _days(current, reboot) >= REBOOT_WATCH_AFTER_DAYS:
        item(
            "reboot-required",
            f"INFRA-01 : redémarrage requis depuis {_days(current, reboot)} jours",
            "Une mise à jour installée attend un redémarrage pour être effective.",
            reboot,
            False,
            {"reboot_required": True},
        )
    summary = (
        "Mises à jour : à jour"
        if not latest.get("pending_count")
        else f"Mises à jour : {latest['pending_count']} en attente"
        f" dont {latest.get('security_count') or 0} de sécurité"
    )
    return _check("system_updates", SYSTEM_NODE, summary, items, known=True)


def tls_certificates(connection: sqlite3.Connection, current: datetime) -> dict:
    latest = _fresh(_snapshots(connection, SYSTEM_NODE, TLS_KIND, current), current)
    if latest is None:
        return _check(
            "tls_certificates",
            SYSTEM_NODE,
            "Certificats : pas de relevé récent",
            [],
            known=False,
        )
    now = to_paris(current)
    items = []
    soonest: int | None = None
    for reading in latest.get("certificates", []):
        expires = to_paris(datetime.fromisoformat(reading["not_after"]))
        remaining = (expires - now).days
        soonest = remaining if soonest is None else min(soonest, remaining)
        if remaining > CERTIFICATE_WATCH_DAYS:
            continue
        expired = expires <= now
        items.append(
            {
                "rule": "tls_certificates",
                "node_id": SYSTEM_NODE,
                "equipment_id": SYSTEM_NODE,
                "subject": f"certificate:{reading['label']}",
                "title": (
                    f"{reading['label']} : certificat expiré"
                    if expired
                    else f"{reading['label']} : certificat expirant "
                    f"dans {remaining} jours"
                ),
                "detail": f"Valable jusqu'au {expires.strftime('%d/%m/%Y')}. "
                "Le renouveler avant cette date ; Ohana ne le fait pas.",
                "since": now.date().isoformat(),
                "urgent": expired or remaining <= CERTIFICATE_URGENT_DAYS,
                "evidence": {
                    "label": reading["label"],
                    "not_after": reading["not_after"],
                },
            }
        )
    summary = (
        "Certificats : aucun relevé"
        if soonest is None
        else f"Certificats : le plus proche expire dans {soonest} jours"
    )
    return _check("tls_certificates", SYSTEM_NODE, summary, items, known=True)


def ha_updates(connection: sqlite3.Connection, current: datetime) -> dict:
    snapshots = _snapshots(connection, HA_NODE, HA_UPDATES_KIND, current)
    latest = _fresh(snapshots, current)
    if latest is None:
        return _check(
            "ha_updates",
            HA_NODE,
            "Home Assistant : pas de relevé récent",
            [],
            known=False,
        )
    items = []
    for update in latest.get("updates", []):
        entity = update["entity_id"]
        since = _running_since(
            snapshots,
            lambda detail, entity=entity: any(
                other["entity_id"] == entity for other in detail.get("updates", [])
            ),
        )
        if since is None or _days(current, since) < HA_UPDATE_WATCH_AFTER_DAYS:
            continue
        name = update.get("title") or entity
        versions = (
            f" ({update['installed_version']} → {update['latest_version']})"
            if update.get("installed_version") and update.get("latest_version")
            else ""
        )
        items.append(
            {
                "rule": "ha_updates",
                "node_id": HA_NODE,
                "equipment_id": HA_NODE,
                "subject": entity,
                "title": (
                    f"Home Assistant : {name} à mettre à jour depuis "
                    f"{_days(current, since)} jours"
                ),
                "detail": f"Mise à jour proposée{versions}. Ohana ne l'installe pas.",
                "since": since.date().isoformat(),
                "urgent": False,
                "evidence": update,
            }
        )
    count = latest.get("count", 0)
    summary = (
        f"Home Assistant : {count} mise(s) à jour proposée(s)"
        if count
        else "Home Assistant : à jour"
    )
    return _check("ha_updates", HA_NODE, summary, items, known=True)


def checks(connection: sqlite3.Connection, current: datetime) -> list[dict[str, Any]]:
    return [
        system_updates(connection, current),
        tls_certificates(connection, current),
        ha_updates(connection, current),
    ]
