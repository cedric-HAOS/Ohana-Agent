"""Configuration of the authenticated Agent administration API."""

from pathlib import Path

from pydantic import Field, IPvAnyAddress, model_validator

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

    @model_validator(mode="after")
    def validate_worker_transport(self) -> "DistributedJobsConfig":
        """Do not expose a worker listener when the job protocol is disabled."""
        if self.worker_tls.enabled and not self.enabled:
            raise ValueError("worker TLS requires distributed jobs to be enabled")
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
