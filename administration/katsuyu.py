"""Minimal Katsuyu worker for explicitly allowlisted distributed jobs."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from administration.models import (
    DistributedJobClaim,
    DistributedJobClaimResult,
    DistributedJobCompletion,
    DistributedJobDocument,
    DistributedJobError,
    DistributedJobStatus,
    SystemHealthIssue,
    SystemHealthParameters,
    SystemHealthResult,
)
from plugins.mqtt.host_health import HostMetrics, SystemHostProbe

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SystemHealthHandler:
    """Collect one bounded deterministic health result on the worker host."""

    probe: SystemHostProbe = field(default_factory=SystemHostProbe)
    disk_usage: Callable[[str], Any] = shutil.disk_usage
    sample_wait: Callable[[float], None] = sleep

    def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Validate the parameter-free contract and collect local resources."""
        SystemHealthParameters.model_validate(parameters)
        self.probe.collect()
        self.sample_wait(0.1)
        metrics = self.probe.collect()
        disk = self.disk_usage("/")

        if metrics.cpu_percent is None:
            raise RuntimeError("CPU utilization is unavailable")
        if metrics.memory_total_bytes is None:
            raise RuntimeError("total memory is unavailable")
        if metrics.memory_available_bytes is None:
            raise RuntimeError("available memory is unavailable")
        if disk.total <= 0:
            raise RuntimeError("disk capacity is unavailable")

        issues = self._issues(metrics, disk)
        result = SystemHealthResult(
            status="DEGRADED" if issues else "OK",
            collected_at=datetime.now(UTC),
            platform=(f"{metrics.operating_system} {metrics.kernel}".strip()[:100]),
            cpu_percent=metrics.cpu_percent,
            memory_total_bytes=metrics.memory_total_bytes,
            memory_available_bytes=metrics.memory_available_bytes,
            disk_total_bytes=int(disk.total),
            disk_free_bytes=int(disk.free),
            temperature_c=metrics.temperature_c,
            issues=issues,
        )
        return result.model_dump(mode="json")

    @staticmethod
    def _issues(metrics: HostMetrics, disk: Any) -> list[SystemHealthIssue]:
        issues: list[SystemHealthIssue] = []

        def high(code: str, label: str, value: float | None, limit: float) -> None:
            if value is not None and value >= limit:
                issues.append(
                    SystemHealthIssue(
                        code=code,
                        message=f"{label}: {value:.1f} % (seuil {limit:.0f} %)",
                    )
                )

        high("resource.cpu.high", "CPU élevé", metrics.cpu_percent, 85)
        high("resource.memory.high", "Mémoire élevée", metrics.memory_percent, 85)
        disk_percent = (disk.used / disk.total * 100) if disk.total else None
        high("resource.disk.high", "Disque occupé", disk_percent, 85)
        if metrics.temperature_c is not None and metrics.temperature_c >= 75:
            issues.append(
                SystemHealthIssue(
                    code="resource.temperature.high",
                    message=(
                        "Température élevée: "
                        f"{metrics.temperature_c:.1f} °C (seuil 75 °C)"
                    ),
                )
            )
        return issues


@dataclass(frozen=True, slots=True)
class KatsuyuHTTPClient:
    """Use Agent's authenticated worker endpoints without another transport."""

    base_url: str
    token: str
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("base_url cannot be empty")
        if not self.token.strip():
            raise ValueError("worker token cannot be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

    def claim(self, payload: dict[str, Any]) -> DistributedJobClaimResult:
        """Claim the oldest job matching Katsuyu's finite handler list."""
        return DistributedJobClaimResult.model_validate(
            self._post("/v1/jobs/claim", payload)
        )

    def complete(
        self,
        job_id: str,
        payload: dict[str, Any],
    ) -> DistributedJobDocument:
        """Submit one validated terminal result to Agent/Tsunade."""
        path = f"/v1/jobs/{quote(job_id, safe='')}/complete"
        return DistributedJobDocument.model_validate(self._post(path, payload))

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            url=f"{self.base_url.rstrip('/')}{path}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(
                f"Agent rejected the worker request with HTTP {error.code}: {detail}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError(
                f"Agent worker endpoint is unavailable: {error}"
            ) from error

        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("Agent returned an invalid worker response") from error
        if not isinstance(value, dict):
            raise RuntimeError("Agent returned a non-object worker response")
        return value


@dataclass(slots=True)
class KatsuyuWorker:
    """Claim and execute only handlers declared by this worker build."""

    client: KatsuyuHTTPClient
    worker_id: str
    handlers: dict[str, SystemHealthHandler] = field(
        default_factory=lambda: {"system.health": SystemHealthHandler()}
    )

    def run_once(self) -> bool:
        """Process at most one job and report a verifiable terminal result."""
        claim = DistributedJobClaim(
            worker_id=self.worker_id,
            supported_types=sorted(self.handlers),
        )
        claimed = self.client.claim(claim.model_dump(mode="json"))
        job = claimed.job
        if job is None:
            return False

        handler = self.handlers.get(job.type)
        if handler is None:
            raise RuntimeError(f"Agent leased unsupported job type {job.type}")

        try:
            result = handler.execute(job.parameters)
            completion = DistributedJobCompletion(
                worker_id=self.worker_id,
                attempt=job.attempt,
                status=DistributedJobStatus.SUCCEEDED,
                result=result,
            )
        except Exception as error:  # noqa: BLE001 - job failures must be reported.
            LOGGER.exception("Katsuyu job %s failed", job.job_id)
            completion = DistributedJobCompletion(
                worker_id=self.worker_id,
                attempt=job.attempt,
                status=DistributedJobStatus.FAILED,
                error=DistributedJobError(
                    code="handler.failed",
                    message=(str(error).strip() or error.__class__.__name__)[:1000],
                    retryable=False,
                ),
            )

        self.client.complete(
            str(job.job_id),
            completion.model_dump(mode="json"),
        )
        return True


def build_parser() -> argparse.ArgumentParser:
    """Build Katsuyu's intentionally small command-line contract."""
    parser = argparse.ArgumentParser(description="Ohana Katsuyu worker")
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path("/etc/ohana-agent/katsuyu.token"),
    )
    parser.add_argument("--worker-id", default=socket.gethostname())
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> None:
    """Poll Tsunade through Agent using the existing worker authentication."""
    arguments = build_parser().parse_args()
    if arguments.poll_seconds <= 0:
        raise SystemExit("--poll-seconds must be greater than zero")
    try:
        token = arguments.token_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise SystemExit(f"Unable to read worker token: {error}") from error
    if not token:
        raise SystemExit("Worker token cannot be empty")

    worker = KatsuyuWorker(
        client=KatsuyuHTTPClient(arguments.base_url, token),
        worker_id=arguments.worker_id,
    )
    while True:
        processed = worker.run_once()
        if arguments.once:
            return
        if not processed:
            sleep(arguments.poll_seconds)


if __name__ == "__main__":
    main()
