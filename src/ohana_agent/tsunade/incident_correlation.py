"""Deterministic correlation between a downstream symptom and an upstream incident."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.tsunade.incident_models import TsunadeIncident

MAXIMUM_DEPENDENCIES = 8

# Messages of a failed host name lookup (``socket.gaierror`` and friends). On
# Konoha, stopping dnsmasq turned DNS, Z-Wave JS, MQTT and telemetry checks
# into "Name or service not known" within a minute.
_NAME_RESOLUTION_FAILURES = re.compile(
    r"name or service not known|no address associated with hostname"
    r"|temporary failure in name resolution|nodename nor servname"
    r"|getaddrinfo failed|could not resolve host|\[errno -[235]\]",
    re.IGNORECASE,
)
NAME_RESOLUTION_SERVICE_TYPES = frozenset({"dns", "dhcp"})


def is_name_resolution_failure(message: str | None) -> bool:
    """Whether an observation failed because a host name did not resolve."""
    return bool(message) and bool(_NAME_RESOLUTION_FAILURES.search(message))


def name_resolution_providers(
    infrastructure: InfrastructureConfig, service_id: str
) -> tuple[str, ...]:
    """Services whose failure explains a name lookup failure elsewhere.

    A lookup failure is not a failure of the service that reported it: the
    resolver (DNS) or the local dnsmasq that serves the LAN names is upstream,
    without any ``depends_on`` declaration.
    """
    return tuple(
        service.id
        for service in infrastructure.services
        if service.id != service_id
        and str(service.type).lower() in NAME_RESOLUTION_SERVICE_TYPES
    )[:MAXIMUM_DEPENDENCIES]


def declared_dependencies(
    infrastructure: InfrastructureConfig,
    service_id: str,
) -> tuple[str, ...]:
    """Return the service ids declared in ``metadata.depends_on``.

    Only an explicit declaration links two services: an unrelated incident that
    merely happens at the same time must never absorb a symptom.
    """
    service = next(
        (item for item in infrastructure.services if item.id == service_id),
        None,
    )
    if service is None:
        return ()
    declared = service.metadata.get("depends_on")
    if isinstance(declared, str):
        declared = [declared]
    if not isinstance(declared, list):
        return ()
    dependencies = dict.fromkeys(
        item.strip()
        for item in declared
        if isinstance(item, str) and item.strip() and item.strip() != service_id
    )
    return tuple(dependencies)[:MAXIMUM_DEPENDENCIES]


def active_upstream_incident(
    incident: TsunadeIncident,
    dependencies: Iterable[str],
    active_incidents: Iterable[TsunadeIncident],
) -> TsunadeIncident | None:
    """Return the oldest active incident on a declared upstream service."""
    upstream_services = set(dependencies)
    candidates = [
        candidate
        for candidate in active_incidents
        if candidate.state == "active"
        and candidate.incident_id != incident.incident_id
        and candidate.service_id in upstream_services
    ]
    return min(candidates, key=lambda item: item.started_at, default=None)


def correlated_upstream_id(incident: TsunadeIncident) -> str | None:
    """Return the upstream incident the latest decision was attached to."""
    decision = incident.latest_decision or {}
    if decision.get("epistemic_status") != "correlated_with_upstream":
        return None
    upstream = decision.get("upstream_incident_id")
    return upstream if isinstance(upstream, str) else None
