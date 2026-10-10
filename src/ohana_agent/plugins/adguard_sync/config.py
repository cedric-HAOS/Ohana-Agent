"""Runtime binding to the infrastructure's local synchronization service."""

from dataclasses import dataclass

from ohana_agent.configuration.adguard_sync import AdGuardSyncPluginConfig
from ohana_agent.infrastructure.service import Service


@dataclass(frozen=True, slots=True)
class AdGuardSyncConfig:
    settings: AdGuardSyncPluginConfig
    services: tuple[Service, ...] = ()
