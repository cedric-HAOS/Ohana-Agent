"""DNS plugin configuration models."""

from pydantic import Field, PositiveFloat, PositiveInt, field_validator

from configuration.base import Config


class DNSPolicyConfig(Config):
    """Health policy applied to the DNS plugin."""

    minimum_healthy_servers: PositiveInt = 1


class DNSPluginConfig(Config):
    """Declarative configuration for the DNS plugin."""

    enabled: bool = True

    # Kept for backward compatibility with existing dns.yaml files.
    # DNS services are now discovered automatically from infrastructure.yaml.
    services: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)

    timeout: PositiveFloat = 2.0
    retries: int = Field(default=1, ge=0)
    interval_seconds: PositiveInt = 60

    policy: DNSPolicyConfig = Field(
        default_factory=DNSPolicyConfig,
    )

    @field_validator("services")
    @classmethod
    def validate_services(
        cls,
        services: list[str],
    ) -> list[str]:
        """Normalize and validate service identifiers."""
        normalized_services = [service.strip() for service in services]

        if any(not service for service in normalized_services):
            raise ValueError("DNS service identifiers must not be empty.")

        return normalized_services

    @field_validator("queries")
    @classmethod
    def validate_queries(
        cls,
        queries: list[str],
    ) -> list[str]:
        """Normalize and validate DNS queries."""
        normalized_queries = [query.strip() for query in queries]

        if any(not query for query in normalized_queries):
            raise ValueError("DNS queries must not be empty.")

        return normalized_queries
