"""Phase 4 hardening: memory, response time, log errors and Home Assistant.

Each rule reads data Tsunade already keeps (daily aggregates, Katsuyu's
daily log checks kept 30 days, hourly Home Assistant samples) and applies
``baseline_drift``. Like the first rules, they only report.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from ohana_agent.tsunade.local_time import to_paris
from ohana_agent.tsunade.preventive_drifts import (
    MAX_BASELINE_DAYS,
    RECENT_DAYS,
    baseline_drift,
)

HISTORY_DAYS = RECENT_DAYS + MAX_BASELINE_DAYS
LATENCY_CAPABILITIES = {
    "dns.resolve": "DNS",
    "mqtt.roundtrip": "MQTT",
    "network.reachable": "Réseau",
}
HA_NODE = "ha-01"
HA_UNAVAILABLE_METRIC = "ha_unavailable_entities"
MAX_LOG_ITEMS = 5

RULES: tuple[dict[str, str], ...] = (
    {
        "id": "memory_growth",
        "title": "Mémoire et swap",
        "rule": (
            "Pic quotidien de mémoire et de swap comparé aux 7 à 28 jours "
            "précédents (même jour de la semaine dès 3 semaines d'historique) : "
            "au moins 4 des 7 derniers jours au-dessus de l'habituel de plus de "
            "5 points, de 10 % ou de trois écarts habituels."
        ),
    },
    {
        "id": "response_time",
        "title": "Temps de réponse",
        "rule": (
            "Temps de réponse moyen quotidien des contrôles DNS, MQTT et réseau "
            "réussis, comparé aux 7 à 28 jours précédents : au moins 4 des 7 "
            "derniers jours plus lents de 20 ms et de 50 % au moins."
        ),
    },
    {
        "id": "log_errors_growth",
        "title": "Erreurs de journaux croissantes",
        "rule": (
            "Occurrences quotidiennes de chaque anomalie des contrôles Katsuyu "
            "(30 jours conservés), hors anomalies acceptées : au moins 4 des 7 "
            "derniers contrôles au-dessus de l'habituel de 20 occurrences et de "
            "50 %."
        ),
    },
    {
        "id": "ha_unavailable_entities",
        "title": "Entités Home Assistant indisponibles",
        "rule": (
            "Minimum quotidien d'entités « unavailable » de HA-01 (relevé "
            "horaire ; le minimum ignore les redémarrages) comparé aux 7 à 28 "
            "jours précédents : au moins 4 des 7 derniers jours au-dessus de "
            "l'habituel de 3 entités et de 20 %."
        ),
    },
)


def _rule(rule_id: str) -> dict[str, str]:
    return next(dict(rule) for rule in RULES if rule["id"] == rule_id)


def _number(value: float) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _series(
    connection: sqlite3.Connection,
    current: datetime,
    metric_filter: str,
    parameter: str,
    column: str,
) -> dict[tuple[str, str], list[tuple[date, float]]]:
    since = (current.date() - timedelta(days=HISTORY_DAYS)).isoformat()
    rows = connection.execute(
        f"""SELECT node_id, metric, day, {column} AS value
        FROM tsunade_trend_daily WHERE {metric_filter} AND day >= ?
        ORDER BY node_id, metric, day""",  # noqa: S608 - fixed fragments.
        (parameter, since),
    ).fetchall()
    series: dict[tuple[str, str], list[tuple[date, float]]] = {}
    for row in rows:
        if row["value"] is None:
            continue
        series.setdefault((row["node_id"], row["metric"]), []).append(
            (date.fromisoformat(row["day"]), float(row["value"]))
        )
    return series


def _check(rule_id: str, nodes: list[dict[str, Any]], items: list[dict[str, Any]]):
    if items:
        state = "watch"
    elif not nodes or all(node["state"] == "insufficient_data" for node in nodes):
        state = "insufficient_data"
    else:
        state = "ok"
    return {**_rule(rule_id), "state": state, "nodes": nodes, "items": items}


def _summary_text(label: str, evaluation: dict[str, Any], unit: str) -> str:
    if evaluation["state"] == "insufficient_data":
        return (
            f"{label} : {evaluation['baseline_days']} jour(s) de référence "
            f"sur 7 nécessaires"
        )
    seasonal = " (même jour de la semaine)" if evaluation["seasonal"] else ""
    return (
        f"{label} : {_number(evaluation['recent_median'])}{unit} cette semaine, "
        f"{_number(evaluation['baseline_median'])}{unit} d'habitude sur "
        f"{evaluation['baseline_days']} j{seasonal}"
    )


def _drift_item(
    rule_id: str,
    node: str,
    subject: str,
    title: str,
    evaluation: dict[str, Any],
    unit: str,
) -> dict[str, Any]:
    return {
        "rule": rule_id,
        "node_id": node,
        "equipment_id": node,
        "subject": subject,
        "title": title,
        "detail": (
            f"{evaluation['days_above']} des 7 derniers jours au-dessus de "
            f"l'habituel ({_number(evaluation['recent_median'])}{unit} contre "
            f"{_number(evaluation['baseline_median'])}{unit}, seuil "
            f"+{_number(evaluation['threshold'])}{unit})."
        ),
        "since": evaluation["above"][0]["day"],
        "evidence": {
            key: evaluation[key]
            for key in (
                "baseline_days",
                "baseline_median",
                "recent_median",
                "threshold",
                "seasonal",
                "above",
            )
        },
        "urgent": False,
    }


def memory_growth(connection: sqlite3.Connection, current: datetime) -> dict:
    series = _series(
        connection,
        current,
        "metric IN (?, 'swap_percent')",
        "memory_percent",
        "maximum",
    )
    nodes, items = [], []
    for (node, metric), points in sorted(series.items()):
        evaluation = baseline_drift(
            points, today=current.date(), absolute_floor=5.0, relative_floor=0.1
        )
        label = "mémoire" if metric == "memory_percent" else "swap"
        nodes.append(
            {
                "node_id": node,
                "metric": metric,
                "state": evaluation["state"],
                "summary": _summary_text(f"{node.upper()} {label}", evaluation, " %"),
            }
        )
        if evaluation["state"] == "watch":
            items.append(
                _drift_item(
                    "memory_growth",
                    node,
                    f"{node}:{metric}",
                    f"{node.upper()} : {label} en hausse",
                    evaluation,
                    " %",
                )
            )
    return _check("memory_growth", nodes, items)


def response_time(connection: sqlite3.Connection, current: datetime) -> dict:
    series = _series(
        connection,
        current,
        "metric LIKE ? AND samples > 0",
        "latency_ms:%",
        "total / samples",
    )
    nodes, items = [], []
    for (node, metric), points in sorted(series.items()):
        _prefix, capability, service = metric.split(":", 2)
        evaluation = baseline_drift(
            points, today=current.date(), absolute_floor=20.0, relative_floor=0.5
        )
        label = f"{LATENCY_CAPABILITIES.get(capability, capability)} {service}"
        nodes.append(
            {
                "node_id": node,
                "metric": metric,
                "state": evaluation["state"],
                "summary": _summary_text(
                    f"{label} ({node.upper()})", evaluation, " ms"
                ),
            }
        )
        if evaluation["state"] == "watch":
            items.append(
                _drift_item(
                    "response_time",
                    node,
                    f"{node}:{capability}:{service}",
                    f"{label} ({node.upper()}) : temps de réponse en hausse",
                    evaluation,
                    " ms",
                )
            )
    return _check("response_time", nodes, items)


def log_errors_growth(connection: sqlite3.Connection, current: datetime) -> dict:
    since = current - timedelta(days=HISTORY_DAYS)
    try:
        rows = connection.execute(
            """SELECT finished_at, result_json FROM distributed_jobs
            WHERE type = 'logs.health_check' AND status = 'SUCCEEDED'
            AND result_json IS NOT NULL
            AND julianday(finished_at) >= julianday(?)
            ORDER BY julianday(finished_at)""",
            (since.isoformat(),),
        ).fetchall()
        accepted = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT source, signature FROM tsunade_accepted_log_signatures"
            )
        }
    except sqlite3.OperationalError:
        return _check("log_errors_growth", [], [])
    checked: dict[str, set[date]] = {}
    counts: dict[tuple[str, str], dict[date, float]] = {}
    for row in rows:
        day = to_paris(datetime.fromisoformat(row[0])).date()
        try:
            result = json.loads(row[1])
        except json.JSONDecodeError:
            continue
        for source in result.get("sources", []):
            source_id = source.get("source")
            if not isinstance(source_id, str) or source.get("truncated"):
                # An incomplete collection proves no absence of an anomaly.
                continue
            checked.setdefault(source_id, set()).add(day)
            for finding in source.get("findings", []):
                key = (source_id, str(finding.get("signature", "")))
                if key in accepted or not key[1]:
                    continue
                daily = counts.setdefault(key, {})
                daily[day] = max(daily.get(day, 0.0), float(finding["occurrences"]))
    nodes, items = [], []
    for source_id in sorted(checked):
        nodes.append(
            {
                "node_id": source_id,
                "state": "ok",
                "summary": (
                    f"{source_id.upper()} : {len(checked[source_id])} contrôle(s) "
                    f"complet(s) sur {HISTORY_DAYS} jours"
                ),
            }
        )
    for (source_id, signature), daily in counts.items():
        # A complete check without the anomaly is a day at zero.
        points = [(day, daily.get(day, 0.0)) for day in sorted(checked[source_id])]
        evaluation = baseline_drift(
            points, today=current.date(), absolute_floor=20.0, relative_floor=0.5
        )
        if evaluation["state"] != "watch":
            continue
        short = signature if len(signature) <= 90 else signature[:87] + "…"
        item = _drift_item(
            "log_errors_growth",
            source_id,
            f"{source_id}:{signature}",
            f"{source_id.upper()} : « {short} » en hausse",
            evaluation,
            "/jour",
        )
        item["evidence"]["signature"] = signature
        items.append(item)
        for node in nodes:
            if node["node_id"] == source_id:
                node["state"] = "watch"
    items.sort(
        key=lambda item: (
            item["evidence"]["recent_median"]
            / max(item["evidence"]["baseline_median"], 1.0)
        ),
        reverse=True,
    )
    return _check("log_errors_growth", nodes, items[:MAX_LOG_ITEMS])


def ha_unavailable_entities(connection: sqlite3.Connection, current: datetime) -> dict:
    series = _series(
        connection, current, "metric = ?", HA_UNAVAILABLE_METRIC, "minimum"
    )
    nodes, items = [], []
    for (node, _metric), points in sorted(series.items()):
        evaluation = baseline_drift(
            points, today=current.date(), absolute_floor=3.0, relative_floor=0.2
        )
        nodes.append(
            {
                "node_id": node,
                "state": evaluation["state"],
                "summary": _summary_text(f"{node.upper()}", evaluation, " entité(s)"),
            }
        )
        if evaluation["state"] != "watch":
            continue
        item = _drift_item(
            "ha_unavailable_entities",
            node,
            node,
            f"{node.upper()} : plus d'entités indisponibles que d'habitude",
            evaluation,
            " entité(s)",
        )
        newly = _newly_unavailable(connection, node, current)
        if newly:
            item["detail"] += (
                " Nouvelles : "
                + ", ".join(newly[:8])
                + ("…" if len(newly) > 8 else ".")
            )
            item["evidence"]["newly_unavailable"] = newly[:50]
        items.append(item)
    return _check("ha_unavailable_entities", nodes, items)


def _newly_unavailable(
    connection: sqlite3.Connection, node: str, current: datetime
) -> list[str]:
    """Entities unavailable in the last sample and in none before the week."""
    rows = connection.execute(
        """SELECT occurred_at, detail_json FROM tsunade_trend_events
        WHERE node_id = ? AND kind = 'ha_unavailable_snapshot'
        ORDER BY occurred_at""",
        (node,),
    ).fetchall()
    if not rows:
        return []
    recent_start = (current.date() - timedelta(days=RECENT_DAYS - 1)).isoformat()
    before: set[str] = set()
    for row in rows:
        if row[0] < recent_start:
            before.update(json.loads(row[1]).get("entities", []))
    latest = json.loads(rows[-1][1]).get("entities", [])
    return sorted(entity for entity in latest if entity not in before)


def correlate_declared(
    items: list[dict[str, Any]],
    dependencies: dict[str, dict[str, list[str]]],
    upstream_incidents: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Drifts on two equipments the owner declared as dependent; never a cause.

    ``dependencies`` maps a downstream equipment to its declared upstream ones
    (with the declaration). A downstream drift is also tied to an open incident
    of its upstream equipment. Nothing is inferred: without a declaration two
    simultaneous drifts on different equipments stay unrelated.
    """
    correlations: list[dict[str, Any]] = []
    by_equipment: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_equipment.setdefault(str(item.get("equipment_id")), []).append(item)
    for downstream, upstreams in sorted(dependencies.items()):
        for upstream, reasons in sorted(upstreams.items()):
            low = by_equipment.get(downstream, [])
            high = by_equipment.get(upstream, [])
            if low and high:
                for item in low:
                    item.setdefault("correlated_upstream", []).extend(
                        f"{other['title']} ({', '.join(reasons)})" for other in high
                    )
                for item in high:
                    item.setdefault("correlated_downstream", []).extend(
                        f"{other['title']} ({', '.join(reasons)})" for other in low
                    )
                correlations.append(
                    {
                        "equipment_id": downstream,
                        "upstream_equipment_id": upstream,
                        "rules": sorted({i["rule"] for i in (*low, *high)}),
                        "titles": [i["title"] for i in (*low, *high)],
                        "declared": reasons,
                        "note": (
                            "Dérives simultanées sur deux équipements dont la "
                            "dépendance est déclarée : un lien est possible, "
                            "la simultanéité ne prouve aucune cause."
                        ),
                    }
                )
            elif low and upstream in (upstream_incidents or {}):
                for item in low:
                    item.setdefault("upstream_incident", []).extend(
                        f"{capability} sur {upstream} ({', '.join(reasons)})"
                        for capability in upstream_incidents[upstream]
                    )
    return correlations


def correlate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drifts on the same equipment at the same time; never a cause."""
    by_equipment: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_equipment.setdefault(str(item.get("equipment_id")), []).append(item)
    correlations = []
    for equipment, grouped in sorted(by_equipment.items()):
        rules = sorted({item["rule"] for item in grouped})
        if len(rules) < 2:
            continue
        titles = [item["title"] for item in grouped]
        for item in grouped:
            others = [title for title in titles if title != item["title"]]
            item["correlated_with"] = others
        correlations.append(
            {
                "equipment_id": equipment,
                "rules": rules,
                "titles": titles,
                "note": (
                    "Dérives simultanées sur le même équipement : un lien est "
                    "possible, la simultanéité ne prouve aucune cause."
                ),
            }
        )
    return correlations
