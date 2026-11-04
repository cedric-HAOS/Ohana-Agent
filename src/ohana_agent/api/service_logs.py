"""Log analysis, accepted anomalies and read-only investigations."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from ohana_agent.configuration.administration import DistributedLogAnalysisConfig
from ohana_agent.contracts.administration import (
    LogsInvestigationAuthorization,
)
from ohana_agent.jobs.job_types import (
    LOCAL_TIMEZONE,
    DistributedJobConflictError,
    paris_instant,
)
from ohana_agent.tsunade.evidence_privacy import redact_session_paths
from ohana_agent.tsunade.incident_models import (
    TsunadeLogWindowExtensionRequest,
)
from ohana_agent.tsunade.investigations import (
    InvestigationRequest,
    investigation_summary,
)

LOGGER = logging.getLogger(__name__)


class LogServiceMixin:
    """Log analysis, accepted anomalies and read-only investigations."""

    def request_log_health_check(
        self,
        *,
        now: datetime | None = None,
        sources: list[str] | tuple[str, ...] | None = None,
        window_hours: int | None = None,
        max_bytes: int | None = None,
        timeout_seconds: int | None = None,
    ) -> object:
        """Ask Katsuyu for one bounded deterministic control chosen by Tsunade."""
        if (
            self.job_repository is None
            or not self.log_analysis_enabled
            or not self.log_sources
        ):
            raise LookupError("Tsunade log analysis is unavailable")
        selected_sources = list(sources or self.log_sources)
        if not selected_sources or any(
            source not in self.log_sources for source in selected_sources
        ):
            raise ValueError("log source is not enabled by Tsunade")
        active = self.job_repository.active_for_incident("logs.health_check", None)
        if active is not None:
            raise DistributedJobConflictError(
                f"log health check is already active as job {active.job_id}"
            )
        current = now or datetime.now(LOCAL_TIMEZONE)
        if current.tzinfo is None or current.utcoffset() is None:
            current = current.replace(tzinfo=LOCAL_TIMEZONE)
        current = paris_instant(current)
        selected_window = window_hours or self.log_window_hours
        window_started = current - timedelta(hours=selected_window)
        baseline: list[dict[str, object]] = []
        previous_sources = self.job_repository.latest_log_health_sources(
            selected_sources,
            window_seconds=int(current.timestamp() - window_started.timestamp()),
        )
        for source in previous_sources:
            if not isinstance(source, dict):
                continue
            for finding in source.get("findings", []):
                if isinstance(finding, dict) and len(baseline) < 192:
                    baseline.append(
                        {
                            "source": source.get("source"),
                            "signature": (
                                redact_session_paths(finding["signature"])
                                if isinstance(finding.get("signature"), str)
                                else finding.get("signature")
                            ),
                            "occurrences": finding.get("occurrences"),
                        }
                    )
        return self.create_job(
            {
                "protocol_version": 1,
                "job_id": str(uuid4()),
                "type": "logs.health_check",
                "created_at": current.isoformat(),
                "parameters": {
                    "sources": selected_sources,
                    "window_started_at": window_started.isoformat(),
                    "window_ended_at": current.isoformat(),
                    "max_bytes_per_source": max_bytes or self.log_max_bytes,
                    "baseline": baseline,
                    "incident_id": None,
                },
                "timeout": timeout_seconds or self.log_timeout_seconds,
            }
        )

    def read_log_analysis(self) -> object:
        """Expose the effective scheduled Tsunade log-control policy."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")
        return {
            "schema_version": 1,
            "enabled": self.log_analysis_enabled,
            "schedule": self.log_analysis_schedule,
            "sources": list(self.log_sources),
            "window_hours": self.log_window_hours,
            "max_bytes_per_source": self.log_max_bytes,
            "timeout_seconds": self.log_timeout_seconds,
        }

    def write_log_analysis(self, payload: dict[str, Any]) -> object:
        """Enable, disable or reschedule the bounded Tsunade log control."""
        if self.job_repository is None:
            raise LookupError("Distributed jobs are unavailable")

        configuration = DistributedLogAnalysisConfig.model_validate(payload)

        if self.on_log_analysis_changed is not None:
            self.on_log_analysis_changed(configuration)

        self.log_analysis_enabled = configuration.enabled
        self.log_analysis_schedule = configuration.schedule
        self.log_sources = configuration.sources
        self.log_window_hours = configuration.window_hours
        self.log_max_bytes = configuration.max_bytes_per_source
        self.log_timeout_seconds = configuration.timeout_seconds

        return self.read_log_analysis()

    def list_accepted_log_signatures(self) -> object:
        """List log anomalies the user accepted as known noise."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        return {
            "schema_version": 1,
            "signatures": self.incident_repository.accepted_log_signatures(),
            "components": self.incident_repository.accepted_log_components(),
        }

    def accept_log_signature(self, payload: dict[str, Any]) -> object:
        """Stop counting one known log anomaly in Tsunade incidents."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        source, signature = self._log_signature_payload(payload)
        self.incident_repository.accept_log_signature(source, signature)
        return self.list_accepted_log_signatures()

    def revoke_log_signature(self, payload: dict[str, Any]) -> object:
        """Count one accepted log anomaly again from the next review."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        source, signature = self._log_signature_payload(payload)
        if not self.incident_repository.revoke_log_signature(source, signature):
            raise LookupError("Signature acceptée introuvable")
        return self.list_accepted_log_signatures()

    def accept_log_component(self, payload: dict[str, Any]) -> object:
        """Stop counting the non-critical anomalies of one component."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        source, component = self._log_component_payload(payload)
        label = payload.get("label")
        self.incident_repository.accept_log_component(
            source, component, label if isinstance(label, str) and label else component
        )
        return self.list_accepted_log_signatures()

    def revoke_log_component(self, payload: dict[str, Any]) -> object:
        """Count one accepted component again from the next review."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        source, component = self._log_component_payload(payload)
        if not self.incident_repository.revoke_log_component(source, component):
            raise LookupError("Composant accepté introuvable")
        return self.list_accepted_log_signatures()

    @staticmethod
    def _log_component_payload(payload: dict[str, Any]) -> tuple[str, str]:
        source = payload.get("source")
        component = payload.get("component")
        if source not in {"infra-01", "ha-01", "linky-01", "zwave-01"}:
            raise ValueError("Source de journaux inconnue")
        if not isinstance(component, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_.\-]{0,79}", component
        ):
            raise ValueError("Composant de journaux invalide")
        return source, component

    @staticmethod
    def _log_signature_payload(payload: dict[str, Any]) -> tuple[str, str]:
        source = payload.get("source")
        signature = payload.get("signature")
        if source not in {"infra-01", "ha-01", "linky-01", "zwave-01"}:
            raise ValueError("Source de journaux inconnue")
        if not isinstance(signature, str) or not 0 < len(signature) <= 1000:
            raise ValueError("Signature d’anomalie invalide")
        return source, signature

    def request_log_investigation(
        self, incident_id: str, payload: dict[str, Any]
    ) -> object:
        """Queue an operator-authorized follow-up for one log incident."""
        if (
            self.job_repository is None
            or not self.log_analysis_enabled
            or not self.log_sources
        ):
            raise LookupError("Tsunade log analysis is unavailable")
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        authorization = LogsInvestigationAuthorization.model_validate(payload)
        incident = self.incident_repository.get(incident_id)
        if incident.state != "active" or incident.capability_id != "logs.health":
            raise ValueError(
                "log investigation requires an active logs.health incident"
            )
        if incident.node_id not in self.log_sources:
            raise ValueError("incident log source is not enabled by Tsunade")
        active = self.job_repository.active_for_incident(
            "logs.investigate", str(incident.incident_id)
        )
        if active is not None:
            raise DistributedJobConflictError(
                f"log investigation is already active as job {active.job_id}"
            )
        current = datetime.now(UTC)
        job = self.create_job(
            {
                "protocol_version": 1,
                "job_id": str(uuid4()),
                "type": "logs.investigate",
                "created_at": current.isoformat(),
                "parameters": {
                    "source": incident.node_id,
                    "window_started_at": (current - timedelta(hours=2)).isoformat(),
                    "window_ended_at": current.isoformat(),
                    "pattern": authorization.pattern,
                    "max_bytes": self.log_max_bytes,
                    "incident_id": str(incident.incident_id),
                },
                "timeout": self.log_timeout_seconds,
            }
        )
        self.incident_repository.append_record(
            incident.incident_id,
            {
                "kind": "investigation",
                "summary": "Analyse approfondie des journaux autorisée",
                "payload": {
                    "job_id": str(job.job_id),
                    "source": incident.node_id,
                    "pattern": authorization.pattern,
                },
            },
        )
        return job

    def extend_log_investigation_window(
        self, incident_id: str, payload: dict[str, Any]
    ) -> object:
        """Authorize the finished log follow-up again over the previous 24 hours."""
        if self.followups is None:
            raise LookupError("Les investigations complémentaires sont indisponibles")
        request = TsunadeLogWindowExtensionRequest.model_validate(payload)
        with self._worker_cycle_lock:
            return self.followups.extend_window(
                incident_id, request.source, request.authorized_by
            )

    def list_investigations(self) -> object:
        if self.investigation_executor is None:
            raise LookupError("Tsunade investigations are unavailable")
        return {
            "schema_version": 1,
            "operations": [
                operation.model_dump(mode="json")
                for operation in self.investigation_executor.catalog()
            ],
        }

    def execute_investigation(self, payload: dict[str, Any]) -> object:
        if self.investigation_executor is None:
            raise LookupError("Tsunade investigations are unavailable")
        request = InvestigationRequest.model_validate(payload)
        result = self.investigation_executor.execute(payload)
        if request.incident_id is not None:
            if self.incident_repository is None:
                raise LookupError("Tsunade incidents are unavailable")
            self.incident_repository.append_record(
                request.incident_id,
                {
                    "kind": "investigation",
                    "summary": investigation_summary(result),
                    "payload": result.model_dump(mode="json"),
                },
            )
        return result
