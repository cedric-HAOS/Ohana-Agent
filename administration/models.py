"""Versioned public models for Ohana-Agent administration."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from ipaddress import IPv4Address, IPv4Interface
from pathlib import PurePosixPath
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAC_ADDRESS_PATTERN = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]+(?:\.(?!-)[A-Za-z0-9-]+)*$"
)


def _workspace_relative_path(value: str) -> str:
    """Require one portable relative path before a backup job is queued."""
    if "\\" in value or ":" in value or value.startswith("/") or value.endswith("/"):
        raise ValueError("path must be a portable workspace-relative file path")
    path = PurePosixPath(value)
    if (
        not path.parts
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("path must be a portable workspace-relative file path")
    return path.as_posix()


class AdministrationModel(BaseModel):
    """Strict mutable model used by administration contracts."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class DHCPSettings(AdministrationModel):
    """Editable dnsmasq DHCP settings."""

    interface: str = Field(min_length=1)
    range_start: IPv4Address
    range_end: IPv4Address
    subnet_mask: IPv4Address
    lease_duration: str = Field(pattern=r"^[1-9][0-9]*[mhdw]$")
    gateway: IPv4Address
    dns_servers: list[IPv4Address] = Field(min_length=1)
    ntp_servers: list[IPv4Address] = Field(min_length=1)
    domain: str = Field(min_length=1)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        """Require a DNS-compatible local domain."""
        if HOSTNAME_PATTERN.fullmatch(value) is None:
            raise ValueError("domain must be a valid DNS name")

        return value.lower()

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        """Require an ordered range sharing the declared subnet."""
        if int(self.range_start) > int(self.range_end):
            raise ValueError("range_start must be lower than or equal to range_end")

        mask = int(self.subnet_mask)
        start_network = int(self.range_start) & mask
        end_network = int(self.range_end) & mask
        gateway_network = int(self.gateway) & mask

        if len({start_network, end_network, gateway_network}) != 1:
            raise ValueError("DHCP range and gateway must belong to the same subnet")

        return self


DHCPReservationCategory = Literal[
    "infrastructure",
    "servers",
    "network",
    "home_automation",
    "critical",
]


class DHCPReservation(AdministrationModel):
    """Static DHCP reservation managed by dnsmasq."""

    mac_address: str
    address: IPv4Address
    hostname: str = Field(min_length=1)
    category: DHCPReservationCategory
    description: str = ""

    @field_validator("mac_address")
    @classmethod
    def normalize_mac_address(cls, value: str) -> str:
        """Normalize and validate a colon-separated MAC address."""
        if MAC_ADDRESS_PATTERN.fullmatch(value) is None:
            raise ValueError("mac_address must use the AA:BB:CC:DD:EE:FF format")

        return value.upper()

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        """Require a DNS-compatible hostname."""
        if HOSTNAME_PATTERN.fullmatch(value) is None:
            raise ValueError("hostname must be a valid DNS name")

        return value.lower()


class DHCPLease(AdministrationModel):
    """Active lease read from dnsmasq's lease database."""

    expires_at: int = Field(ge=0)
    mac_address: str
    address: IPv4Address
    hostname: str | None = None
    client_id: str | None = None

    @field_validator("mac_address")
    @classmethod
    def normalize_mac_address(cls, value: str) -> str:
        """Normalize a lease MAC address."""
        if MAC_ADDRESS_PATTERN.fullmatch(value) is None:
            raise ValueError("lease mac_address is invalid")

        return value.upper()


class DHCPConfiguration(AdministrationModel):
    """Complete DHCP administration document."""

    schema_version: Literal[1] = 1
    implementation: Literal["dnsmasq"] = "dnsmasq"
    server_node_id: str = Field(min_length=1)
    settings: DHCPSettings
    reservations: list[DHCPReservation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_reservations(self) -> Self:
        """Reject duplicate MAC, address and hostname reservations."""
        for field_name in ("mac_address", "address", "hostname"):
            values = [
                str(getattr(reservation, field_name)).lower()
                for reservation in self.reservations
            ]

            if len(values) != len(set(values)):
                raise ValueError(f"reservations contain duplicate {field_name} values")

        return self


class DHCPAdministrationState(DHCPConfiguration):
    """DHCP configuration enriched with currently active leases."""

    leases: list[DHCPLease] = Field(default_factory=list)


NetworkMethod = Literal["manual", "auto"]


class AgentNetworkSettings(AdministrationModel):
    """Editable IPv4 settings for the Agent host."""

    interface: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]{1,32}$")
    method: NetworkMethod = "manual"
    address: IPv4Interface | None = None
    gateway: IPv4Address | None = None
    dns_servers: list[IPv4Address] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manual_configuration(self) -> Self:
        """Require a complete and coherent static IPv4 configuration."""
        if self.method == "auto":
            return self

        if self.address is None or self.gateway is None or not self.dns_servers:
            raise ValueError(
                "manual network configuration requires address, gateway and DNS servers"
            )

        if self.gateway not in self.address.network:
            raise ValueError("gateway must belong to the configured IPv4 subnet")

        if self.address.ip in {
            self.address.network.network_address,
            self.address.network.broadcast_address,
        }:
            raise ValueError("address cannot be the network or broadcast address")

        return self


class AgentNetworkPendingChange(AdministrationModel):
    """Pending network transaction protected by an automatic rollback."""

    transaction_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expires_at: datetime
    requested: AgentNetworkSettings


class AgentNetworkState(AdministrationModel):
    """Active NetworkManager state exposed to Vision."""

    schema_version: Literal[1] = 1
    available: bool = True
    interface: str = Field(min_length=1)
    connection_name: str = Field(min_length=1)
    method: NetworkMethod
    address: IPv4Interface | None = None
    gateway: IPv4Address | None = None
    dns_servers: list[IPv4Address] = Field(default_factory=list)
    active: bool
    state: str = Field(min_length=1)
    pending_change: AgentNetworkPendingChange | None = None


class AgentNetworkChangeRequest(AdministrationModel):
    """Candidate network configuration and rollback delay."""

    schema_version: Literal[1] = 1
    settings: AgentNetworkSettings
    rollback_seconds: int | None = Field(default=None, ge=30, le=300)


class AgentNetworkChange(AdministrationModel):
    """Network transaction created after applying a candidate configuration."""

    schema_version: Literal[1] = 1
    transaction_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expires_at: datetime
    state: AgentNetworkState


class AdministrationCapabilities(AdministrationModel):
    """Administration functions explicitly exposed by Ohana-Agent."""

    schema_version: Literal[1] = 1
    agent_version: str = Field(min_length=1)
    operations: list[str] = Field(default_factory=list)


class DistributedJobStatus(StrEnum):
    """Stable states exposed by the distributed job protocol."""

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    WAITING_WORKER = "WAITING_WORKER"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


class DistributedJobCreate(AdministrationModel):
    """Versioned request accepted from Tsunade."""

    protocol_version: Literal[1] = 1
    job_id: UUID
    type: str = Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
    created_at: datetime
    parameters: dict[str, Any]
    timeout: int = Field(ge=1, le=86_400)

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        """Reject ambiguous local timestamps in a distributed protocol."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


class DistributedJobError(AdministrationModel):
    """Bounded structured failure returned by a worker."""

    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    message: str = Field(min_length=1, max_length=1000)
    retryable: bool = False


class DistributedJobProgress(AdministrationModel):
    """Bounded progress snapshot reported by the owning worker."""

    percent: float = Field(ge=0, le=100)
    stage: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    message: str | None = Field(default=None, max_length=500)


class DistributedJobDocument(AdministrationModel):
    """Current durable state of one distributed job."""

    protocol_version: Literal[1] = 1
    job_id: UUID
    type: str
    created_at: datetime
    parameters: dict[str, Any]
    timeout: int
    status: DistributedJobStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error: DistributedJobError | None = None
    worker_id: str | None = None
    attempt: int = Field(default=0, ge=0)
    lease_expires_at: datetime | None = None
    progress: DistributedJobProgress | None = None


class DistributedJobClaim(AdministrationModel):
    """Katsuyu request for one compatible queued job."""

    protocol_version: Literal[1] = 1
    worker_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    supported_types: list[str] = Field(min_length=1, max_length=32)


class DistributedJobClaimResult(AdministrationModel):
    """Claim response; an empty job asks the worker to poll later."""

    protocol_version: Literal[1] = 1
    job: DistributedJobDocument | None = None


class DistributedJobHeartbeat(AdministrationModel):
    """Lease renewal sent only by the worker owning the attempt."""

    protocol_version: Literal[1] = 1
    worker_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    attempt: int = Field(ge=1)
    progress: DistributedJobProgress | None = None


class DistributedWorkerRegistration(AdministrationModel):
    """Authenticated Katsuyu registration and capability announcement."""

    protocol_version: Literal[1] = 1
    worker_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    capabilities: list[str] = Field(min_length=1, max_length=32)
    platform: str = Field(min_length=1, max_length=100)
    worker_version: str = Field(min_length=1, max_length=40)


class DistributedWorkerAvailability(StrEnum):
    """Operational availability exposed independently from job states."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    WAKING = "WAKING"


class DistributedWorkerDocument(DistributedWorkerRegistration):
    """Latest durable registration known by Agent/Tsunade."""

    registered_at: datetime
    last_seen_at: datetime
    availability: DistributedWorkerAvailability
    woken_by_ohana: bool = False
    wake_requested_at: datetime | None = None
    wake_deadline_at: datetime | None = None


class DistributedWorkerCollection(AdministrationModel):
    """Workers registered with the Agent control plane."""

    protocol_version: Literal[1] = 1
    workers: list[DistributedWorkerDocument] = Field(default_factory=list)


class DistributedWorkerPairingRequest(DistributedWorkerRegistration):
    """Bounded identity and capabilities proposed by an unpaired installer."""


class DistributedWorkerPairingCreated(AdministrationModel):
    """One-time polling material shown only to the requesting installer."""

    protocol_version: Literal[1] = 1
    pairing_id: UUID
    polling_secret: str = Field(min_length=32, max_length=128)
    verification_code: str = Field(pattern=r"^[A-Z0-9]{4}-[A-Z0-9]{4}$")
    expires_at: datetime
    tls_ca_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class DistributedWorkerPairingPoll(AdministrationModel):
    """Proof that a poll belongs to the installer that opened the request."""

    protocol_version: Literal[1] = 1
    polling_secret: str = Field(min_length=32, max_length=128)


class DistributedWorkerPairingDocument(DistributedWorkerRegistration):
    """Administrative view of a pending or completed pairing request."""

    pairing_id: UUID
    verification_code: str = Field(pattern=r"^[A-Z0-9]{4}-[A-Z0-9]{4}$")
    status: Literal["PENDING", "APPROVED", "CONSUMED", "EXPIRED", "REJECTED"]
    created_at: datetime
    expires_at: datetime
    tls_ca_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class DistributedWorkerPairingCollection(AdministrationModel):
    """Pairing requests visible to Tsunade through Vision."""

    protocol_version: Literal[1] = 1
    pairings: list[DistributedWorkerPairingDocument] = Field(default_factory=list)


class DistributedWorkerPairingResult(AdministrationModel):
    """Poll result; a credential is returned exactly once after approval."""

    protocol_version: Literal[1] = 1
    pairing_id: UUID
    status: Literal["PENDING", "APPROVED", "CONSUMED", "EXPIRED", "REJECTED"]
    expires_at: datetime
    worker_token: str | None = Field(default=None, min_length=32, max_length=128)


class DistributedJobCompletion(DistributedJobHeartbeat):
    """Terminal result submitted by the worker owning the attempt."""

    status: Literal[
        DistributedJobStatus.SUCCEEDED,
        DistributedJobStatus.FAILED,
    ]
    result: dict[str, Any] | None = None
    error: DistributedJobError | None = None

    @model_validator(mode="after")
    def validate_terminal_payload(self) -> Self:
        """Require exactly the payload associated with the terminal state."""
        if self.status == DistributedJobStatus.SUCCEEDED:
            if self.result is None or self.error is not None:
                raise ValueError("SUCCEEDED requires result and forbids error")
        elif self.result is not None or self.error is None:
            raise ValueError("FAILED requires error and forbids result")
        return self


class SystemHealthParameters(AdministrationModel):
    """Parameter-free deterministic health collection on the Katsuyu host."""


class SystemHealthIssue(AdministrationModel):
    """One bounded issue detected by the Katsuyu health handler."""

    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    message: str = Field(min_length=1, max_length=500)


class SystemHealthResult(AdministrationModel):
    """Strict result expected from the first Katsuyu MVP handler."""

    status: Literal["OK", "DEGRADED"]
    collected_at: datetime
    platform: str = Field(min_length=1, max_length=100)
    cpu_percent: float = Field(ge=0, le=100)
    memory_total_bytes: int = Field(ge=1)
    memory_available_bytes: int = Field(ge=0)
    disk_total_bytes: int = Field(ge=1)
    disk_free_bytes: int = Field(ge=0)
    temperature_c: float | None = Field(default=None, ge=-50, le=150)
    issues: list[SystemHealthIssue] = Field(default_factory=list, max_length=32)

    @field_validator("collected_at")
    @classmethod
    def require_aware_collection_time(cls, value: datetime) -> datetime:
        """Require an unambiguous timestamp from the remote worker."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_health_consistency(self) -> Self:
        """Reject impossible resource values and contradictory summaries."""
        if self.memory_available_bytes > self.memory_total_bytes:
            raise ValueError("memory_available_bytes cannot exceed total memory")
        if self.disk_free_bytes > self.disk_total_bytes:
            raise ValueError("disk_free_bytes cannot exceed total disk")
        if self.status == "OK" and self.issues:
            raise ValueError("OK cannot include issues")
        if self.status == "DEGRADED" and not self.issues:
            raise ValueError("DEGRADED requires at least one issue")
        return self


class BackupCompressParameters(AdministrationModel):
    """Compress one workspace file to deterministic gzip without a shell."""

    source: str = Field(min_length=1, max_length=500)
    destination: str = Field(min_length=1, max_length=500)
    compression_level: int = Field(default=6, ge=1, le=9)

    @field_validator("source", "destination")
    @classmethod
    def validate_paths(cls, value: str) -> str:
        return _workspace_relative_path(value)

    @model_validator(mode="after")
    def require_distinct_paths(self) -> Self:
        if self.source == self.destination:
            raise ValueError("source and destination must differ")
        return self


class BackupCompressResult(AdministrationModel):
    """Verifiable compression result returned by Katsuyu."""

    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_size: int = Field(ge=0)
    destination_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    destination_size: int = Field(ge=1)


class BackupEncryptParameters(AdministrationModel):
    """Encrypt one workspace file for one explicit age recipient."""

    source: str = Field(min_length=1, max_length=500)
    destination: str = Field(min_length=1, max_length=500)
    recipient: str = Field(min_length=20, max_length=200, pattern=r"^age1[0-9a-z]+$")

    @field_validator("source", "destination")
    @classmethod
    def validate_paths(cls, value: str) -> str:
        return _workspace_relative_path(value)

    @model_validator(mode="after")
    def require_distinct_paths(self) -> Self:
        if self.source == self.destination:
            raise ValueError("source and destination must differ")
        return self


class BackupEncryptResult(AdministrationModel):
    """Verifiable encrypted artifact metadata."""

    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_size: int = Field(ge=0)
    destination_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    destination_size: int = Field(ge=1)
    recipient: str = Field(min_length=20, max_length=200, pattern=r"^age1[0-9a-z]+$")


class BackupVerifyParameters(AdministrationModel):
    """Verify one workspace file against mandatory expected metadata."""

    path: str = Field(min_length=1, max_length=500)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_size: int | None = Field(default=None, ge=0)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _workspace_relative_path(value)


class BackupVerifyResult(AdministrationModel):
    """Deterministic integrity decision."""

    valid: bool
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    sha256_matches: bool
    size_matches: bool | None = None


class InfraBackupParameters(AdministrationModel):
    """Agent-owned INFRA backup request without arbitrary paths or secrets."""

    backup_id: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}Z$")
    recipient: str = Field(min_length=20, max_length=200, pattern=r"^age1[0-9a-z]+$")
    compression_level: int = Field(default=6, ge=1, le=9)


class InfraBackupResult(AdministrationModel):
    """Remote receipt produced by the deterministic Katsuyu backup handler."""

    backup_id: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}Z$")
    remote_path: str = Field(min_length=1, max_length=1000)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_size: int = Field(ge=1)
    compressed_size: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    deleted_remote_backups: int = Field(default=0, ge=0)
    duration_seconds: float = Field(ge=0)
    cpu_seconds: float = Field(ge=0)
    peak_working_set_bytes: int | None = Field(default=None, ge=0)
    logical_io_read_bytes: int = Field(ge=0)
    logical_io_written_bytes: int = Field(ge=0)


class AiInferenceEvidence(AdministrationModel):
    """One bounded evidence fragment supplied by Tsunade, never an instruction."""

    source: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    content: str = Field(min_length=1, max_length=16_000)


class AiInferenceParameters(AdministrationModel):
    """Minimal diagnostic request; raw permanent log collections are forbidden."""

    task: Literal["technical.diagnosis"] = "technical.diagnosis"
    question: str = Field(min_length=1, max_length=2_000)
    evidence: list[AiInferenceEvidence] = Field(min_length=1, max_length=8)
    max_output_tokens: int = Field(default=1_024, ge=128, le=1_024)

    @model_validator(mode="after")
    def bound_total_evidence(self) -> Self:
        if sum(len(item.content) for item in self.evidence) > 48_000:
            raise ValueError("ai.inference evidence cannot exceed 48000 characters")
        return self


class AiInferenceFinding(AdministrationModel):
    """One evidence-backed finding returned by the local model."""

    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z0-9_.-]+$")
    evidence: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)


class AiInferenceMetrics(AdministrationModel):
    """Measured local runtime cost returned for observability and comparison."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    ttft_ms: float = Field(ge=0)
    tokens_per_second: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)


class AiInferenceResult(AdministrationModel):
    """Strict diagnostic result; recommendations never execute an operation."""

    verdict: Literal["OK", "KO", "INSUFFICIENT_CONTEXT"]
    generated_at: datetime
    model_id: str = Field(min_length=1, max_length=120)
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: str = Field(min_length=1, max_length=1_000)
    findings: list[AiInferenceFinding] = Field(default_factory=list, max_length=16)
    missing_context: list[str] = Field(default_factory=list, max_length=16)
    recommended_investigation: list[str] = Field(default_factory=list, max_length=16)
    metrics: AiInferenceMetrics

    @model_validator(mode="after")
    def validate_diagnostic_consistency(self) -> Self:
        if self.verdict == "OK" and self.findings:
            raise ValueError("OK cannot contain anomaly findings")
        if self.verdict == "KO" and not self.findings:
            raise ValueError("KO requires at least one finding")
        if self.verdict == "INSUFFICIENT_CONTEXT" and not self.missing_context:
            raise ValueError("INSUFFICIENT_CONTEXT requires missing_context")
        bounded_text = [
            *self.missing_context,
            *self.recommended_investigation,
        ]
        if any(not value.strip() or len(value) > 500 for value in bounded_text):
            raise ValueError("diagnostic list entries must contain 1 to 500 characters")
        return self


PluginAdministrationStatus = Literal[
    "active",
    "idle",
    "disabled",
    "degraded",
    "error",
]


class PluginAdministrationState(AdministrationModel):
    """Editable plugin configuration enriched with runtime information."""

    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    version: str = Field(min_length=1)
    lifecycle_state: str = Field(min_length=1)
    status: PluginAdministrationStatus
    enabled: bool = True
    capabilities: list[str] = Field(default_factory=list)
    interval_seconds: int = Field(default=0, ge=0)
    task_count: int = Field(default=0, ge=0)
    execution_count: int = Field(default=0, ge=0)
    last_execution_at: datetime | None = None
    next_run_at: datetime | None = None
    last_error: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)


class PluginAdministrationCollection(AdministrationModel):
    """Collection returned by the plugin administration endpoint."""

    schema_version: Literal[1] = 1
    plugins: list[PluginAdministrationState] = Field(default_factory=list)


class PluginConfigurationUpdate(AdministrationModel):
    """Complete editable document accepted for one plugin."""

    schema_version: Literal[1] = 1
    enabled: bool = True
    configuration: dict[str, Any] = Field(default_factory=dict)


class PluginTestResult(AdministrationModel):
    """Result of an immediate plugin capability test."""

    schema_version: Literal[1] = 1
    plugin_id: str = Field(min_length=1)
    success: bool
    check: str | None = None
    message: str | None = None
    latency_ms: float = Field(ge=0)
    tested_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
