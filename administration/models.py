"""Versioned public models for Ohana-Agent administration."""

from __future__ import annotations

import re
from datetime import datetime
from ipaddress import IPv4Address, IPv4Interface
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAC_ADDRESS_PATTERN = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]+(?:\.(?!-)[A-Za-z0-9-]+)*$"
)


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
