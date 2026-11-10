"""Severity of an incident: how bad the observation is, and what it concerns.

An observation only tells whether a check failed. Whether that failure is
critical for the house is declared in the infrastructure: the ``critical`` flag
of a service, and for an equipment either its own ``critical`` metadata or the
critical services it hosts. A failure the infrastructure declares secondary
opens a degraded incident. What the infrastructure does not describe (the host
itself, backups) keeps the severity its source chose.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import yaml

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.configuration.loaders.infrastructure_loader import (
    InfrastructureLoader,
)
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.incident_models import IncidentSeverity

LOGGER = logging.getLogger(__name__)

SeverityPolicy = Callable[[Observation], IncidentSeverity | None]


def observed_severity(observation: Observation) -> IncidentSeverity | None:
    """Severity from the status alone: every failed check is critical."""
    if observation.status is ObservationStatus.DEGRADED:
        return "degraded"
    if observation.status is ObservationStatus.UNHEALTHY:
        return "critical"
    return None


def declared_severity(
    observation: Observation, infrastructure: InfrastructureConfig | None
) -> IncidentSeverity | None:
    """Severity of a fault, weighted by what the infrastructure declares."""
    severity = observed_severity(observation)
    if severity != "critical" or infrastructure is None:
        return severity
    for service in infrastructure.services:
        if (service.node, service.id) == (observation.node, observation.service):
            return "critical" if service.critical else "degraded"
    if observation.metadata.get("target_type") == "device":
        device_id = observation.metadata.get("device_id") or observation.service
        return "critical" if _critical_device(infrastructure, device_id) else "degraded"
    return severity


def _critical_device(infrastructure: InfrastructureConfig, device_id: object) -> bool:
    topology = infrastructure.topology
    for device in topology.devices if topology is not None else ():
        if device.id != device_id:
            continue
        declared = device.metadata.get("critical")
        if isinstance(declared, bool):
            return declared
        return device.node is not None and any(
            service.node == device.node and service.enabled and service.critical
            for service in infrastructure.services
        )
    # Not declared (a discovered Z-Wave node, for instance): never critical.
    return False


class DeclaredSeverity:
    """Severity policy reading the infrastructure file, reloaded when it changes."""

    def __init__(self, infrastructure_path: Path) -> None:
        self.infrastructure_path = infrastructure_path
        self._loaded_mtime_ns: int | None = None
        self._infrastructure: InfrastructureConfig | None = None

    def __call__(self, observation: Observation) -> IncidentSeverity | None:
        if observation.status is not ObservationStatus.UNHEALTHY:
            return observed_severity(observation)
        return declared_severity(observation, self._current())

    def _current(self) -> InfrastructureConfig | None:
        try:
            mtime_ns = self.infrastructure_path.stat().st_mtime_ns
            if mtime_ns != self._loaded_mtime_ns:
                self._infrastructure = InfrastructureLoader().load(
                    self.infrastructure_path
                )
                self._loaded_mtime_ns = mtime_ns
        except (OSError, ValueError, yaml.YAMLError) as error:
            # An unreadable declaration must not hide a failure: without it
            # the fault keeps the severity of its status.
            LOGGER.warning(
                "Infrastructure unreadable for incident severity: %s",
                type(error).__name__,
            )
            self._infrastructure = None
            self._loaded_mtime_ns = None
        return self._infrastructure
