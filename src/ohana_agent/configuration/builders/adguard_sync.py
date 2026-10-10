"""Bind the synchronization observer to its INFRA-01 service."""

from ohana_agent.configuration.adguard_sync import AdGuardSyncPluginConfig
from ohana_agent.infrastructure import Infrastructure, ServiceType
from ohana_agent.plugins.adguard_sync.config import AdGuardSyncConfig


class AdGuardSyncConfigurationBuilder:
    def build(
        self, infrastructure: Infrastructure, config: AdGuardSyncPluginConfig
    ) -> AdGuardSyncConfig:
        services = tuple(infrastructure.find_services(ServiceType.ADGUARD_SYNC))
        if len(services) > 1:
            raise ValueError(
                "Only one local AdGuard synchronization service is supported"
            )
        if config.enabled and not any(service.enabled for service in services):
            raise ValueError(
                "An enabled adguard_sync infrastructure service is required"
            )
        return AdGuardSyncConfig(settings=config, services=services)
