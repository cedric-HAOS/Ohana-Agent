"""Companion (Shizune) summary, requests, pairing and devices."""

from __future__ import annotations

import logging
from typing import Any

from ohana_agent.contracts.administration import DistributedJobStatus
from ohana_agent.tsunade.companion_overview import (
    log_check_summary,
    logs_overview,
    services_overview,
)
from ohana_agent.tsunade.incident_summary import (
    incident_assessment,
)

LOGGER = logging.getLogger(__name__)


# The essential of the host's package updates: counts, dates and progress.
# The package list stays in Vision.
_COMPANION_SYSTEM_UPDATE_FIELDS = (
    "status",
    "message",
    "pending_count",
    "security_count",
    "kernel_pending",
    "lists_refreshed_at",
    "lists_age_days",
    "lists_stale",
    "reboot_required",
    "read_at",
    "helper",
)


class CompanionServiceMixin:
    """Companion (Shizune) summary, requests, pairing and devices."""

    def read_companion_summary(self) -> object:
        """Return the smallest useful Konoha overview for a personal companion."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        self._settle_for_read(reconcile=True)
        requests = self.incident_repository.list_user_requests(state="pending").requests
        incidents = self.incident_repository.list(state="active", limit=500)
        incidents.sort(
            key=lambda incident: (
                incident_assessment(incident)["priority"],
                incident.started_at,
            )
        )
        totals = self.incident_repository.statistics()
        active_count = totals["incident_count"] - totals["resolved_incident_count"]
        severity = (
            "critical"
            if any(incident.severity == "critical" for incident in incidents)
            else "degraded"
            if incidents
            else "healthy"
        )
        last_checked_at = max(
            (incident.last_observed_at for incident in incidents),
            default=None,
        )
        latest_log_health = None
        last_log_success = None
        if self.job_repository is not None:
            last_log_success = self.job_repository.latest_for_incident(
                "logs.health_check", None, DistributedJobStatus.SUCCEEDED
            )
            latest_log_health = self.job_repository.latest_for_incident(
                "logs.health_check", None
            )
            if latest_log_health is not None:
                candidate = (
                    latest_log_health.finished_at or latest_log_health.created_at
                )
                if last_checked_at is None or candidate > last_checked_at:
                    last_checked_at = candidate
        pending_count = len(requests)
        message = (
            "Aucune autorisation en attente"
            if pending_count == 0
            else f"{pending_count} décision(s) attendent votre réponse"
        )
        attention = [
            {
                "incident_id": str(incident.incident_id),
                "equipment": incident.equipment_id,
                "capability": incident.capability_id,
                "severity": incident.severity,
                "message": incident.message,
                "started_at": incident.started_at.isoformat(),
                "assessment": incident_assessment(incident),
            }
            for incident in incidents[:20]
        ]
        return {
            "schema_version": 1,
            "konoha_state": severity,
            "tsunade_message": message,
            "pending_requests": pending_count,
            "last_checked_at": last_checked_at.isoformat() if last_checked_at else None,
            "attention": attention,
            "active_count": active_count,
            "attention_truncated": active_count > len(attention),
            "preventive": self._companion_preventive(),
            "services": self._companion_services(),
            "logs": logs_overview(
                incidents,
                {str(request.incident_id) for request in requests},
                self._accepted_log_counts(),
                last_log_success.finished_at if last_log_success is not None else None,
                last_check=log_check_summary(latest_log_health),
            ),
        }

    def read_companion_system_updates(self) -> dict[str, Any]:
        """Whether the Agent's host is up to date, without the package list."""
        state = self.read_system_updates()
        return {
            "schema_version": 1,
            **{field: state.get(field) for field in _COMPANION_SYSTEM_UPDATE_FIELDS},
        }

    def request_companion_system_update(
        self, action: str, companion_id: str | None
    ) -> object:
        """A paired companion asks for the fixed refresh or upgrade helper.

        Same refusals as from Vision: the companion chooses neither a package
        nor an option, and the machine is never restarted.
        """
        result = self.request_system_update(action)
        LOGGER.info(
            "System update %s requested by companion %s: %s",
            action,
            companion_id,
            "started" if result.get("started") else "already running",
        )
        return result

    def _companion_services(self) -> dict[str, Any]:
        """The essential services at a glance, from Agent's own latest checks."""
        try:
            configuration = self.infrastructure_repository.read()
            service_types = {
                service.id: service.type
                for service in configuration.services
                if service.enabled
            }
        except Exception:  # noqa: BLE001 - incidents stay readable without it.
            LOGGER.exception("Unable to read the services for the companion")
            service_types = {}
        states = self.incident_repository.capability_states()
        if (
            "adguard_sync" in service_types.values()
            and self.plugin_repository is not None
        ):
            try:
                enabled = self.plugin_repository.read("adguard_sync").enabled
            except Exception:  # No configuration evidence means no reassuring tile.
                enabled = False
            if not enabled:
                states = [
                    row
                    for row in states
                    if service_types.get(row["service"]) != "adguard_sync"
                ]
        return services_overview(states, service_types)

    def _accepted_log_counts(self) -> dict[str, int]:
        """Known-noise entries the user accepted, per log source."""
        counts: dict[str, int] = {}
        for entry in (
            *self.incident_repository.accepted_log_components(),
            *self.incident_repository.accepted_log_signatures(),
        ):
            counts[entry["source"]] = counts.get(entry["source"], 0) + 1
        return counts

    def _companion_preventive(self) -> dict[str, Any] | None:
        """The essential of the preventive synthesis; Vision has the detail."""
        if self.preventive_monitor is None:
            return None
        try:
            summary = self.preventive_monitor.summary()
        except Exception:  # noqa: BLE001 - incidents stay readable without it.
            LOGGER.exception("Unable to evaluate the preventive synthesis")
            return None
        return {
            "status": summary["status"],
            "watch": [
                {"title": item["title"], "urgent": item["urgent"]}
                for item in summary["watch"]
            ],
            "conclusion": summary["conclusion"],
            "generated_at": summary["generated_at"],
        }

    def read_companion_requests(self, state: str = "pending") -> object:
        """Expose structured Tsunade questions without technical incident payloads."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        self._settle_for_read(refresh=False, reconcile=True)
        return self.incident_repository.list_user_requests(
            state="all" if state == "all" else "pending"
        )

    def read_companion_activity(self) -> object:
        """Return a bounded human timeline, not Vision's technical history."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        activity = [
            item.model_dump(mode="json")
            for item in self.incident_repository.companion_activity(limit=20)
        ]
        if self.job_repository is not None:
            latest = self.job_repository.latest_for_incident("logs.health_check", None)
            if latest is not None and latest.finished_at is not None:
                activity.append(
                    {
                        "activity_id": f"log-control-{latest.job_id}",
                        "occurred_at": latest.finished_at.isoformat(),
                        "kind": "investigation",
                        "title": "Contrôle quotidien des journaux terminé",
                        "detail": (
                            "Aucune anomalie relevée dans les sources contrôlées."
                            if latest.result and latest.result.get("status") == "OK"
                            else "Anomalies ou sources indisponibles à examiner."
                        )
                        if latest.status.value == "SUCCEEDED"
                        else "Le contrôle n’a pas abouti.",
                        "incident_id": None,
                    }
                )
        activity.sort(key=lambda item: str(item["occurred_at"]), reverse=True)
        return {"schema_version": 1, "activity": activity[:20]}

    def respond_companion_request(
        self,
        request_id: str,
        device_id: str,
        payload: dict[str, Any],
    ) -> object:
        """Route a structured answer through Tsunade and Agent's existing executor."""
        if self.incident_repository is None:
            raise LookupError("Tsunade incidents are unavailable")
        if set(payload) != {"choice"}:
            raise ValueError("Seul le choix proposé par Tsunade est accepté")
        choice = str(payload.get("choice") or "").upper()
        request = self.incident_repository.get_user_request(request_id)
        response = {
            "choice": choice,
            "source": "shizune",
            "answered_by": device_id,
        }
        if choice == "LATER":
            return self.incident_repository.defer_user_request(request_id, response)
        if request.kind == "investigation_authorization":
            if self.followups is None:
                raise LookupError(
                    "Les investigations complémentaires sont indisponibles"
                )
            with self._worker_cycle_lock:
                return self.followups.respond(request_id, device_id, choice)
        if request.kind != "repair_authorization":
            return self.incident_repository.answer_user_request(request_id, response)
        repair_id = self.incident_repository.user_request_action_reference(request_id)
        if repair_id is None:
            raise ValueError("La demande ne référence aucune action autorisée")
        if choice == "AUTHORIZE":
            self.authorize_incident_repair(
                str(request.incident_id),
                {
                    "repair_id": repair_id,
                    "source": "shizune",
                    "authorized_by": device_id,
                },
            )
        elif choice == "REFUSE":
            self.incident_repository.refuse_repair(
                request.incident_id,
                repair_id,
                source="shizune",
                answered_by=device_id,
            )
        else:
            raise ValueError("Cette réponse n’est pas valable pour la réparation")
        return self.incident_repository.get_user_request(request_id)

    def create_companion_pairing(self, payload: dict[str, Any]) -> object:
        if (
            self.companion_repository is None
            or self.companion_ca_sha256 is None
            or self.companion_ca_certificate_pem is None
        ):
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.create_pairing(
            payload,
            tls_ca_sha256=self.companion_ca_sha256,
            tls_ca_certificate_pem=self.companion_ca_certificate_pem,
        )

    def poll_companion_pairing(
        self, pairing_id: str, payload: dict[str, Any]
    ) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.poll_pairing(pairing_id, payload)

    def list_companion_pairings(self) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.list_pairings()

    def approve_companion_pairing(self, pairing_id: str) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.approve_pairing(pairing_id)

    def reject_companion_pairing(self, pairing_id: str) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.reject_pairing(pairing_id)

    def list_companion_devices(self) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.list_devices()

    def revoke_companion_device(self, device_id: str) -> object:
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.revoke(device_id)

    def register_companion_notifications(
        self, device_id: str, payload: dict[str, Any]
    ) -> object:
        """Bind APNs delivery only to the authenticated companion session."""
        if self.companion_repository is None:
            raise LookupError("L’association Shizune est indisponible")
        return self.companion_repository.register_push_token(device_id, payload)
