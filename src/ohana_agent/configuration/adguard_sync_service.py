"""Provision the local supervision service when the updated Agent starts."""

from pathlib import Path

from ohana_agent.configuration.infrastructure import InfrastructureConfig, ServiceConfig
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository


def ensure_adguard_sync_service(path: Path, *, node_id: str) -> InfrastructureConfig:
    """Add only the missing service; preserve existing operator configuration."""
    repository = InfrastructureConfigurationRepository(path)
    configuration = repository.read()
    if any(service.type == "adguard_sync" for service in configuration.services):
        return configuration
    if not any(node.id == node_id for node in configuration.nodes):
        return configuration
    identifier = "adguard-sync"
    if any(service.id == identifier for service in configuration.services):
        raise ValueError("The adguard-sync identifier belongs to another service")
    service = ServiceConfig(
        id=identifier,
        name="Synchronisation AdGuard",
        type="adguard_sync",
        node=node_id,
        implementation="adguardhome-sync",
        enabled=True,
        critical=False,
    )
    return repository.write(
        configuration.model_copy(
            update={
                "services": [*configuration.services, service],
            }
        )
    )
