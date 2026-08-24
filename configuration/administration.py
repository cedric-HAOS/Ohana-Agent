"""Configuration of the authenticated Agent administration API."""

from pathlib import Path
from typing import Literal

from pydantic import Field, IPvAnyAddress, field_validator, model_validator

from configuration.base import Config


class DHCPAdministrationConfig(Config):
    """Paths used to manage the installed dnsmasq DHCP service."""

    enabled: bool = True
    server_node_id: str = "infra-01"
    main_config_path: Path = Path("/etc/dnsmasq.d/00-ohana.conf")
    infrastructure_reservations_path: Path = Path(
        "/etc/dnsmasq.d/10-infrastructure.conf"
    )
    server_reservations_path: Path = Path("/etc/dnsmasq.d/20-serveurs.conf")
    network_reservations_path: Path = Path(
        "/etc/dnsmasq.d/30-infrastructure-reseau.conf"
    )
    home_automation_reservations_path: Path = Path(
        "/etc/dnsmasq.d/40-passerelles-domotiques.conf"
    )
    critical_reservations_path: Path = Path(
        "/etc/dnsmasq.d/50-equipements-critiques.conf"
    )
    leases_path: Path = Path("/var/lib/misc/dnsmasq.leases")
    validation_command: tuple[str, ...] | None = (
        "/usr/sbin/dnsmasq",
        "--test",
    )
    reload_request_path: Path = Path("/run/ohana-agent/dhcp-reload.request")


class NetworkAdministrationConfig(Config):
    """Restricted helper used to administer the Agent host network."""

    enabled: bool = False
    helper_path: Path = Path("/usr/local/sbin/ohana-network-helper")
    sudo_path: Path = Path("/usr/bin/sudo")
    rollback_seconds: int = Field(default=90, ge=30, le=300)


class DistributedWorkerTLSConfig(Config):
    """Dedicated HTTPS listener exposed only to Katsuyu workers."""

    enabled: bool = False
    host: IPvAnyAddress = IPvAnyAddress("0.0.0.0")
    port: int = Field(default=8766, ge=1, le=65535)
    certificate_file: Path = Path("/etc/ohana-agent/tls/worker.crt")
    private_key_file: Path = Path("/etc/ohana-agent/tls/worker.key")
    ca_certificate_file: Path = Path("/etc/ohana-agent/tls/ca.crt")


class APNsConfig(Config):
    """Optional direct Apple Push Notification provider configuration."""

    enabled: bool = False
    environment: Literal["development", "production"] = "production"
    team_id: str | None = Field(default=None, pattern=r"^[A-Z0-9]{10}$")
    key_id: str | None = Field(default=None, pattern=r"^[A-Z0-9]{10}$")
    bundle_id: str = Field(default="fr.ohana.Shizune", min_length=3, max_length=255)
    private_key_file: Path = Path("/etc/ohana-agent/shizune-apns.p8")
    timeout_seconds: float = Field(default=5.0, ge=1.0, le=15.0)

    @model_validator(mode="after")
    def validate_enabled_provider(self) -> "APNsConfig":
        if self.enabled and (self.team_id is None or self.key_id is None):
            raise ValueError("enabled APNs requires team_id and key_id")
        return self


class CompanionTLSConfig(Config):
    """Limited HTTPS listener used only by paired personal companions."""

    enabled: bool = False
    host: IPvAnyAddress = IPvAnyAddress("0.0.0.0")
    port: int = Field(default=8767, ge=1, le=65535)
    certificate_file: Path = Path("/etc/ohana-agent/tls/worker.crt")
    private_key_file: Path = Path("/etc/ohana-agent/tls/worker.key")
    ca_certificate_file: Path = Path("/etc/ohana-agent/tls/ca.crt")
    credential_ttl_days: int = Field(default=90, ge=1, le=365)
    push: APNsConfig = Field(default_factory=APNsConfig)


class WakeOnLanConfig(Config):
    """Optional, bounded Wake-on-LAN policy for one Katsuyu host."""

    enabled: bool = False
    worker_id: str = "katsuyu-bubule"
    mac_address: str | None = None
    broadcast_address: IPvAnyAddress = IPvAnyAddress("255.255.255.255")
    port: int = Field(default=9, ge=1, le=65535)
    wait_timeout_seconds: int = Field(default=180, ge=10, le=1800)
    available_for_seconds: int = Field(default=30, ge=10, le=600)

    @field_validator("worker_id")
    @classmethod
    def validate_worker_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Wake-on-LAN worker_id cannot be empty")
        return normalized

    @field_validator("mac_address")
    @classmethod
    def normalize_mac_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_enabled_policy(self) -> "WakeOnLanConfig":
        if self.enabled and self.mac_address is None:
            raise ValueError("enabled Wake-on-LAN requires a MAC address")
        return self


class DistributedLogAnalysisConfig(Config):
    """Bounded periodic Tsunade log-control policy."""

    enabled: bool = False
    schedule: str = "0 5 * * *"
    sources: tuple[Literal["ha-01", "linky-01", "zwave-01"], ...] = (
        "ha-01",
        "linky-01",
        "zwave-01",
    )
    window_hours: int = Field(default=24, ge=1, le=48)
    max_bytes_per_source: int = Field(
        default=2 * 1024 * 1024, ge=1024, le=4 * 1024 * 1024
    )
    timeout_seconds: int = Field(default=900, ge=60, le=3600)

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) > 3 or len(set(value)) != len(value):
            raise ValueError("log sources must contain one to three unique targets")
        return value


class DistributedJobsConfig(Config):
    """Durable Tsunade-to-Katsuyu job protocol configuration."""

    enabled: bool = False
    database_path: Path = Path("/var/lib/ohana-agent/distributed-jobs.db")
    worker_token_file: Path = Path("/etc/ohana-agent/katsuyu.token")
    lease_seconds: int = Field(default=60, ge=10, le=3600)
    waiting_worker_after_seconds: int = Field(default=30, ge=0, le=3600)
    retention_days: int = Field(default=30, ge=1, le=365)
    max_active_jobs: int = Field(default=1000, ge=1, le=100_000)
    worker_tls: DistributedWorkerTLSConfig = Field(
        default_factory=DistributedWorkerTLSConfig
    )
    wake_on_lan: WakeOnLanConfig = Field(default_factory=WakeOnLanConfig)
    logs: DistributedLogAnalysisConfig = Field(
        default_factory=DistributedLogAnalysisConfig
    )

    @model_validator(mode="after")
    def validate_worker_transport(self) -> "DistributedJobsConfig":
        """Do not expose a worker listener when the job protocol is disabled."""
        if self.worker_tls.enabled and not self.enabled:
            raise ValueError("worker TLS requires distributed jobs to be enabled")
        if self.logs.enabled and not self.enabled:
            raise ValueError("distributed log analysis requires jobs to be enabled")
        return self


class AdministrationConfig(Config):
    """Agent administration endpoint configuration."""

    enabled: bool = False
    host: IPvAnyAddress = IPvAnyAddress("127.0.0.1")
    port: int = Field(default=8765, ge=1, le=65535)
    token_file: Path = Path("/etc/ohana-agent/management.token")
    dhcp: DHCPAdministrationConfig = Field(default_factory=DHCPAdministrationConfig)
    network: NetworkAdministrationConfig = Field(
        default_factory=NetworkAdministrationConfig
    )
    jobs: DistributedJobsConfig = Field(default_factory=DistributedJobsConfig)
    companion: CompanionTLSConfig = Field(default_factory=CompanionTLSConfig)
