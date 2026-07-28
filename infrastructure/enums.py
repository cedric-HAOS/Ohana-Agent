"""Infrastructure model enumerations."""

from enum import StrEnum


class EndpointType(StrEnum):
    """Supported infrastructure endpoint types."""

    IP = "ip"
    HOSTNAME = "hostname"
    URL = "url"
    MQTT = "mqtt"


class ServiceType(StrEnum):
    """Supported infrastructure service types."""

    DNS = "dns"
    DHCP = "dhcp"
    MQTT = "mqtt"
    HTTP = "http"
    HTTPS = "https"
    NTP = "ntp"
    HOME_ASSISTANT = "home_assistant"
    ZWAVE = "zwave"
    WIREGUARD = "wireguard"
    SHELLY_TELEMETRY = "shelly_telemetry"
    TELEINFORMATION = "teleinformation"


class HealthStatus(StrEnum):
    """Generic health status for infrastructure objects."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
