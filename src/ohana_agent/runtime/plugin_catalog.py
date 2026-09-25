"""The ten production plugins, declared once each."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ohana_agent.configuration.administration import DHCPAdministrationConfig
from ohana_agent.configuration.backup import BackupPluginConfig
from ohana_agent.configuration.builders import (
    BackupConfigurationBuilder,
    DHCPConfigurationBuilder,
    DNSConfigurationBuilder,
    HomeAssistantTelemetryConfigurationBuilder,
    MQTTConfigurationBuilder,
    NetworkConfigurationBuilder,
    NTPConfigurationBuilder,
    TeleinformationConfigurationBuilder,
    WireGuardConfigurationBuilder,
    ZWaveConfigurationBuilder,
)
from ohana_agent.configuration.dhcp import DHCPPluginConfig
from ohana_agent.configuration.dns import DNSPluginConfig
from ohana_agent.configuration.home_assistant_telemetry import (
    HomeAssistantTelemetryPluginConfig,
)
from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.configuration.loaders import (
    BackupConfigLoader,
    DHCPConfigLoader,
    DNSConfigLoader,
    HomeAssistantTelemetryConfigLoader,
    MQTTConfigLoader,
    NetworkConfigLoader,
    NTPConfigLoader,
    TeleinformationConfigLoader,
    WireGuardConfigLoader,
    ZWaveConfigLoader,
)
from ohana_agent.configuration.mqtt_plugin import MQTTPluginConfig
from ohana_agent.configuration.network import NetworkPluginConfig
from ohana_agent.configuration.ntp import NTPPluginConfig
from ohana_agent.configuration.teleinformation import TeleinformationPluginConfig
from ohana_agent.configuration.wireguard import WireGuardPluginConfig
from ohana_agent.configuration.zwave import ZWavePluginConfig
from ohana_agent.observation import ObserverResult
from ohana_agent.plugins.backup.config import BackupConfig
from ohana_agent.plugins.backup.coordinator import BackupCoordinator
from ohana_agent.plugins.backup.plugin import BackupPlugin
from ohana_agent.plugins.dhcp.check import DHCPCheck
from ohana_agent.plugins.dhcp.config import DHCPConfig
from ohana_agent.plugins.dhcp.plugin import DHCPPlugin
from ohana_agent.plugins.dns.check import DNSCheck
from ohana_agent.plugins.dns.config import DNSConfig
from ohana_agent.plugins.dns.plugin import DNSPlugin
from ohana_agent.plugins.home_assistant_telemetry.check import (
    HomeAssistantTelemetryCheck,
)
from ohana_agent.plugins.home_assistant_telemetry.config import (
    HomeAssistantTelemetryConfig,
)
from ohana_agent.plugins.home_assistant_telemetry.plugin import (
    HomeAssistantTelemetryPlugin,
)
from ohana_agent.plugins.mqtt.check import MQTTCheck
from ohana_agent.plugins.mqtt.config import MQTTConfig
from ohana_agent.plugins.mqtt.home_assistant_publisher import MQTTHomeAssistantPublisher
from ohana_agent.plugins.mqtt.plugin import MQTTPlugin
from ohana_agent.plugins.network.check import NetworkCheck
from ohana_agent.plugins.network.config import NetworkConfig
from ohana_agent.plugins.network.plugin import NetworkPlugin
from ohana_agent.plugins.ntp.check import NTPCheck
from ohana_agent.plugins.ntp.config import NTPConfig
from ohana_agent.plugins.ntp.plugin import NTPPlugin
from ohana_agent.plugins.teleinformation.check import TeleinformationCheck
from ohana_agent.plugins.teleinformation.config import TeleinformationConfig
from ohana_agent.plugins.teleinformation.plugin import TeleinformationPlugin
from ohana_agent.plugins.wireguard.check import WireGuardCheck
from ohana_agent.plugins.wireguard.config import WireGuardConfig
from ohana_agent.plugins.wireguard.plugin import WireGuardPlugin
from ohana_agent.plugins.zwave.check import ZWaveCheck
from ohana_agent.plugins.zwave.config import ZWaveConfig
from ohana_agent.plugins.zwave.plugin import ZWavePlugin
from ohana_agent.runtime.plugin_specs import PluginSpec
from ohana_agent.scheduler import CronTrigger, IntervalTrigger, Task

LOCAL_SCHEDULE_TIMEZONE = ZoneInfo("Europe/Paris")


def build_dhcp_tasks(
    *,
    dhcp_config: DHCPConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled status observation per DHCP service."""
    return [
        Task(
            id=f"dhcp.status:{server.name}",
            name=f"Observe DHCP service {server.name}",
            command="dhcp.status",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "server": server.address,
                "port": server.port,
                "service_id": server.name,
            },
            metadata={
                "managed_by": "dhcp",
                "node_id": server.node_id,
                "service_id": server.name,
                "server": server.address,
                "port": server.port,
            },
        )
        for server in dhcp_config.servers
        if server.enabled
    ]


def build_dns_tasks(
    *,
    dns_config: DNSConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled observation per DNS service and query."""
    tasks: list[Task] = []

    for server in dns_config.servers:
        if not server.enabled:
            continue

        for query_index, hostname in enumerate(dns_config.queries):
            tasks.append(
                Task(
                    id=(f"dns.resolve:{server.name}:{query_index}:{hostname}"),
                    name=(f"Resolve {hostname} through {server.name}"),
                    command="dns.resolve",
                    trigger=IntervalTrigger(
                        interval=timedelta(seconds=interval_seconds),
                        start_at=start_at,
                    ),
                    arguments={
                        "hostname": hostname,
                        "server": server.address,
                        "service_id": server.name,
                    },
                    metadata={
                        "managed_by": "dns",
                        "node_id": server.node_id,
                        "service_id": server.name,
                        "server": server.address,
                    },
                )
            )

    return tasks


def build_ntp_tasks(
    *,
    ntp_config: NTPConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled observation per enabled NTP service."""
    return [
        Task(
            id=f"ntp.query:{server.name}",
            name=f"Query time through {server.name}",
            command="ntp.query",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "server": server.address,
                "port": server.port,
                "service_id": server.name,
            },
            metadata={
                "managed_by": "ntp",
                "node_id": server.node_id,
                "service_id": server.name,
                "server": server.address,
                "port": server.port,
            },
        )
        for server in ntp_config.servers
        if server.enabled
    ]


def build_mqtt_tasks(
    *,
    mqtt_config: MQTTConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled round-trip observation per enabled MQTT broker."""
    return [
        Task(
            id=f"mqtt.roundtrip:{broker.name}",
            name=f"Test MQTT round trip through {broker.name}",
            command="mqtt.roundtrip",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "broker": broker.address,
                "port": broker.port,
                "service_id": broker.name,
            },
            metadata={
                "managed_by": "mqtt",
                "node_id": broker.node_id,
                "service_id": broker.name,
                "broker": broker.address,
                "port": broker.port,
            },
        )
        for broker in mqtt_config.brokers
        if broker.enabled
    ]


def build_network_tasks(
    *,
    network_config: NetworkConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build presence observations spread evenly across one interval."""
    devices = [device for device in network_config.devices if device.enabled]

    if not devices:
        return []

    spacing_seconds = interval_seconds / len(devices)

    return [
        Task(
            id=f"network.reachable:{device.name}",
            name=f"Check network presence of {device.label}",
            command="network.reachable",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at + timedelta(seconds=device_index * spacing_seconds),
            ),
            arguments={
                "address": device.address,
                "device_id": device.name,
                "label": device.label,
                "node_id": device.node_id,
            },
            metadata={
                "managed_by": "network",
                "node_id": device.node_id or device.name,
                "device_id": device.name,
                "address": device.address,
            },
        )
        for device_index, device in enumerate(devices)
    ]


def build_zwave_tasks(
    *,
    zwave_config: ZWaveConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled health observation per Z-Wave service."""
    return [
        Task(
            id=f"zwave.status:{service.name}",
            name=f"Check Z-Wave controller {service.name}",
            command="zwave.status",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "url": service.url,
                "service_id": service.name,
            },
            metadata={
                "managed_by": "zwave",
                "node_id": service.node_id,
                "service_id": service.name,
                "url": service.url,
            },
        )
        for service in zwave_config.services
        if service.enabled
    ]


def build_wireguard_tasks(
    *,
    wireguard_config: WireGuardConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one scheduled inspection per Freebox WireGuard service."""
    return [
        Task(
            id=f"wireguard.status:{service.name}",
            name=f"Inspect Freebox WireGuard service {service.name}",
            command="wireguard.status",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "base_url": service.base_url,
                "server_name": service.server_name,
                "service_id": service.name,
            },
            metadata={
                "managed_by": "wireguard",
                "node_id": service.node_id,
                "service_id": service.name,
                "base_url": service.base_url,
                "server_name": service.server_name,
            },
        )
        for service in wireguard_config.services
        if service.enabled
    ]


def build_home_assistant_telemetry_tasks(
    *,
    home_assistant_telemetry_config: HomeAssistantTelemetryConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one telemetry freshness observation per declared service."""
    return [
        Task(
            id=f"home_assistant.telemetry.freshness:{service.name}",
            name=f"Check Home Assistant telemetry service {service.name}",
            command="home_assistant_telemetry.freshness",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "service_id": service.name,
                "service_name": service.label,
                "node_id": service.node_id,
                "primary_entity_id": service.primary_entity_id,
                "secondary_entity_id": service.secondary_entity_id,
                "maximum_age_seconds": service.maximum_age_seconds,
            },
            metadata={
                "managed_by": "home_assistant_telemetry",
                "service_id": service.name,
                "service_name": service.label,
                "node_id": service.node_id,
                "primary_entity_id": service.primary_entity_id,
                "secondary_entity_id": service.secondary_entity_id,
                "maximum_age_seconds": service.maximum_age_seconds,
            },
        )
        for service in home_assistant_telemetry_config.services
        if service.enabled
    ]


def build_teleinformation_tasks(
    *,
    teleinformation_config: TeleinformationConfig,
    interval_seconds: int,
    start_at: datetime,
) -> list[Task]:
    """Build one Linky Téléinformation observation per declared service."""
    return [
        Task(
            id=f"teleinformation.freshness:{service.name}",
            name=f"Check Linky teleinformation service {service.name}",
            command="teleinformation.freshness",
            trigger=IntervalTrigger(
                interval=timedelta(seconds=interval_seconds),
                start_at=start_at,
            ),
            arguments={
                "service_id": service.name,
                "service_name": service.label,
                "node_id": service.node_id,
                "source_id": service.source_id,
                "meter_id": service.meter_id,
                "apparent_power_entity_id": service.apparent_power_entity_id,
                "tariff_entity_id": service.tariff_entity_id,
                "blue_off_peak_entity_id": service.blue_off_peak_entity_id,
                "blue_peak_entity_id": service.blue_peak_entity_id,
                "white_off_peak_entity_id": service.white_off_peak_entity_id,
                "white_peak_entity_id": service.white_peak_entity_id,
                "red_off_peak_entity_id": service.red_off_peak_entity_id,
                "red_peak_entity_id": service.red_peak_entity_id,
                "maximum_age_seconds": service.maximum_age_seconds,
            },
            metadata={
                "managed_by": "teleinformation",
                "service_id": service.name,
                "service_name": service.label,
                "node_id": service.node_id,
                "source_id": service.source_id,
                "meter_id": service.meter_id,
                "apparent_power_entity_id": service.apparent_power_entity_id,
                "tariff_entity_id": service.tariff_entity_id,
                "maximum_age_seconds": service.maximum_age_seconds,
            },
        )
        for service in teleinformation_config.services
        if service.enabled
    ]


def build_backup_tasks(
    *, backup_config: BackupConfig, schedule_timezone: ZoneInfo | None = None
) -> list[Task]:
    """Build independent HAOS and INFRA-01 backup tasks."""
    tasks = [
        Task(
            id=f"backup.run:{target.id}",
            name=f"Back up {target.label}",
            command="backup.run",
            trigger=CronTrigger(target.schedule, timezone=schedule_timezone),
            arguments={
                "target_id": target.id,
                "device_id": target.id,
                "node_id": target.id,
            },
            metadata={
                "managed_by": "backup",
                "target_id": target.id,
                "device_id": target.id,
                "schedule": target.schedule,
            },
        )
        for target in backup_config.targets
        if target.enabled
    ]
    if backup_config.infra_01.enabled:
        tasks.append(
            Task(
                id="backup.run:infra-01",
                name="Back up INFRA-01",
                command="backup.run",
                trigger=CronTrigger(
                    backup_config.infra_01.schedule,
                    timezone=schedule_timezone,
                ),
                arguments={
                    "target_id": "infra-01",
                    "device_id": "infra-01",
                    "node_id": "infra-01",
                },
                metadata={
                    "managed_by": "backup",
                    "target_id": "infra-01",
                    "device_id": "infra-01",
                    "schedule": backup_config.infra_01.schedule,
                },
            )
        )
    return tasks


def _enabled(items):
    return [item for item in items if item.enabled]


def test_dhcp_plugin(plugin: DHCPPlugin) -> ObserverResult:
    servers = _enabled(plugin.config.servers)

    if not servers:
        raise ValueError("The DHCP plugin has no enabled DHCP service.")

    return plugin.execute(
        server=servers[0].address,
        port=servers[0].port,
        service_id=servers[0].name,
    )


def test_dns_plugin(plugin: DNSPlugin) -> ObserverResult:
    servers = _enabled(plugin.servers)

    if not plugin.config.queries:
        raise ValueError("The DNS plugin has no configured query.")

    if not servers:
        raise ValueError("The DNS plugin has no enabled DNS service.")

    return plugin.execute(
        hostname=plugin.config.queries[0],
        server=servers[0].address,
    )


def test_ntp_plugin(plugin: NTPPlugin) -> ObserverResult:
    servers = _enabled(plugin.config.servers)

    if not servers:
        raise ValueError("The NTP plugin has no enabled NTP service.")

    return plugin.execute(
        server=servers[0].address,
        port=servers[0].port,
    )


def test_mqtt_plugin(plugin: MQTTPlugin) -> ObserverResult:
    brokers = _enabled(plugin.config.brokers)

    if not brokers:
        raise ValueError("The MQTT plugin has no enabled MQTT service.")

    return plugin.execute(
        broker=brokers[0].address,
        port=brokers[0].port,
        service_id=brokers[0].name,
    )


def test_network_plugin(plugin: NetworkPlugin) -> ObserverResult:
    devices = _enabled(plugin.config.devices)

    if not devices:
        raise ValueError("The network plugin has no addressable device.")

    device = devices[0]
    return plugin.test(
        address=device.address,
        device_id=device.name,
        label=device.label,
        node_id=device.node_id,
    )


def test_zwave_plugin(plugin: ZWavePlugin) -> ObserverResult:
    services = _enabled(plugin.config.services)

    if not services:
        raise ValueError("The Z-Wave plugin has no enabled Z-Wave service.")

    return plugin.execute(url=services[0].url)


def test_wireguard_plugin(plugin: WireGuardPlugin) -> ObserverResult:
    services = _enabled(plugin.config.services)

    if not services:
        raise ValueError("The WireGuard plugin has no enabled WireGuard service.")

    service = services[0]
    return plugin.execute(
        service_id=service.name,
        base_url=service.base_url,
        server_name=service.server_name,
    )


def test_home_assistant_telemetry_plugin(
    plugin: HomeAssistantTelemetryPlugin,
) -> ObserverResult:
    services = _enabled(plugin.config.services)

    if not services:
        raise ValueError(
            "The Home Assistant telemetry"
            "plugin has no enabled Home"
            "Assistant telemetry service."
        )

    service = services[0]
    return plugin.execute(
        service_id=service.name,
        service_name=service.label,
        node_id=service.node_id,
        primary_entity_id=service.primary_entity_id,
        secondary_entity_id=service.secondary_entity_id,
        maximum_age_seconds=service.maximum_age_seconds,
    )


def test_teleinformation_plugin(plugin: TeleinformationPlugin) -> ObserverResult:
    services = _enabled(plugin.config.services)

    if not services:
        raise ValueError(
            "The Téléinformation plugin has no enabled Téléinformation service."
        )

    service = services[0]
    return plugin.execute(
        service_id=service.name,
        service_name=service.label,
        node_id=service.node_id,
        source_id=service.source_id,
        meter_id=service.meter_id,
        apparent_power_entity_id=service.apparent_power_entity_id,
        tariff_entity_id=service.tariff_entity_id,
        blue_off_peak_entity_id=service.blue_off_peak_entity_id,
        blue_peak_entity_id=service.blue_peak_entity_id,
        white_off_peak_entity_id=service.white_off_peak_entity_id,
        white_peak_entity_id=service.white_peak_entity_id,
        red_off_peak_entity_id=service.red_off_peak_entity_id,
        red_peak_entity_id=service.red_peak_entity_id,
        maximum_age_seconds=service.maximum_age_seconds,
    )


def _reconfigure_mqtt(
    plugin: MQTTPlugin,
    config: MQTTConfig,
    infrastructure_config: InfrastructureConfig | None,
) -> None:
    plugin.reconfigure(config, infrastructure=infrastructure_config)


def production_plugin_specs(
    *,
    dhcp_service_config: DHCPAdministrationConfig,
    infrastructure_config: InfrastructureConfig,
    dhcp_check: DHCPCheck | None = None,
    network_check: NetworkCheck | None = None,
    zwave_check: ZWaveCheck | None = None,
    wireguard_check: WireGuardCheck | None = None,
    home_assistant_telemetry_check: HomeAssistantTelemetryCheck | None = None,
    teleinformation_check: TeleinformationCheck | None = None,
    backup_coordinator: BackupCoordinator | None = None,
) -> tuple[PluginSpec, ...]:
    """Declare the production plugins in registration order.

    ``infrastructure_config`` only seeds the MQTT Home Assistant publisher;
    later infrastructure changes reach it through ``_reconfigure_mqtt``.
    """
    return (
        PluginSpec(
            identifier="dhcp",
            display_name="DHCP",
            capabilities=("dhcp.status",),
            configuration_model=DHCPPluginConfig,
            load_configuration=DHCPConfigLoader().load,
            build_config=lambda infrastructure, _, plugin_config: (
                DHCPConfigurationBuilder().build(
                    infrastructure,
                    plugin_config,
                    server_node_id=dhcp_service_config.server_node_id,
                    main_config_path=dhcp_service_config.main_config_path,
                    leases_path=dhcp_service_config.leases_path,
                )
            ),
            create_plugin=lambda config: DHCPPlugin(
                check=dhcp_check or DHCPCheck(), config=config
            ),
            build_tasks=lambda config, plugin_config, now: build_dhcp_tasks(
                dhcp_config=config,
                interval_seconds=plugin_config.interval_seconds,
                start_at=now,
            ),
            test_plugin=test_dhcp_plugin,
        ),
        PluginSpec(
            identifier="dns",
            display_name="DNS",
            capabilities=("dns.resolve",),
            configuration_model=DNSPluginConfig,
            load_configuration=DNSConfigLoader().load,
            build_config=lambda infrastructure, _, plugin_config: (
                DNSConfigurationBuilder().build(infrastructure, plugin_config)
            ),
            create_plugin=lambda config: DNSPlugin(check=DNSCheck(), config=config),
            build_tasks=lambda config, plugin_config, now: build_dns_tasks(
                dns_config=config,
                interval_seconds=plugin_config.interval_seconds,
                start_at=now,
            ),
            test_plugin=test_dns_plugin,
        ),
        PluginSpec(
            identifier="ntp",
            display_name="NTP",
            capabilities=("ntp.query",),
            configuration_model=NTPPluginConfig,
            load_configuration=NTPConfigLoader().load,
            build_config=lambda infrastructure, _, plugin_config: (
                NTPConfigurationBuilder().build(infrastructure, plugin_config)
            ),
            create_plugin=lambda config: NTPPlugin(check=NTPCheck(), config=config),
            build_tasks=lambda config, plugin_config, now: build_ntp_tasks(
                ntp_config=config,
                interval_seconds=plugin_config.interval_seconds,
                start_at=now,
            ),
            test_plugin=test_ntp_plugin,
        ),
        PluginSpec(
            identifier="mqtt",
            display_name="MQTT",
            capabilities=("mqtt.roundtrip",),
            configuration_model=MQTTPluginConfig,
            load_configuration=MQTTConfigLoader().load,
            build_config=lambda infrastructure, _, plugin_config: (
                MQTTConfigurationBuilder().build(infrastructure, plugin_config)
            ),
            create_plugin=lambda config: MQTTPlugin(
                check=MQTTCheck(),
                config=config,
                home_assistant_publisher=MQTTHomeAssistantPublisher(
                    config=config,
                    infrastructure=infrastructure_config,
                ),
            ),
            build_tasks=lambda config, plugin_config, now: build_mqtt_tasks(
                mqtt_config=config,
                interval_seconds=plugin_config.interval_seconds,
                start_at=now,
            ),
            test_plugin=test_mqtt_plugin,
            reconfigure=_reconfigure_mqtt,
        ),
        PluginSpec(
            identifier="network",
            display_name="Présence réseau",
            capabilities=("network.reachable",),
            configuration_model=NetworkPluginConfig,
            load_configuration=NetworkConfigLoader().load,
            build_config=lambda _, infrastructure_config, plugin_config: (
                NetworkConfigurationBuilder().build(
                    infrastructure_config, plugin_config
                )
            ),
            create_plugin=lambda config: NetworkPlugin(
                check=network_check or NetworkCheck(), config=config
            ),
            build_tasks=lambda config, plugin_config, now: build_network_tasks(
                network_config=config,
                interval_seconds=plugin_config.interval_seconds,
                start_at=now,
            ),
            test_plugin=test_network_plugin,
        ),
        PluginSpec(
            identifier="zwave",
            display_name="Z-Wave",
            capabilities=("zwave.status",),
            configuration_model=ZWavePluginConfig,
            load_configuration=ZWaveConfigLoader().load,
            build_config=lambda infrastructure, _, plugin_config: (
                ZWaveConfigurationBuilder().build(infrastructure, plugin_config)
            ),
            create_plugin=lambda config: ZWavePlugin(
                check=zwave_check or ZWaveCheck(), config=config
            ),
            build_tasks=lambda config, plugin_config, now: build_zwave_tasks(
                zwave_config=config,
                interval_seconds=plugin_config.interval_seconds,
                start_at=now,
            ),
            test_plugin=test_zwave_plugin,
        ),
        PluginSpec(
            identifier="wireguard",
            display_name="WireGuard",
            capabilities=("wireguard.status",),
            configuration_model=WireGuardPluginConfig,
            load_configuration=WireGuardConfigLoader().load,
            build_config=lambda infrastructure, _, plugin_config: (
                WireGuardConfigurationBuilder().build(infrastructure, plugin_config)
            ),
            create_plugin=lambda config: WireGuardPlugin(
                check=wireguard_check or WireGuardCheck(), config=config
            ),
            build_tasks=lambda config, plugin_config, now: build_wireguard_tasks(
                wireguard_config=config,
                interval_seconds=plugin_config.interval_seconds,
                start_at=now,
            ),
            test_plugin=test_wireguard_plugin,
        ),
        PluginSpec(
            identifier="home_assistant_telemetry",
            display_name="Télémétrie Home Assistant",
            capabilities=("home_assistant.telemetry.freshness",),
            configuration_model=HomeAssistantTelemetryPluginConfig,
            load_configuration=HomeAssistantTelemetryConfigLoader().load,
            build_config=lambda infrastructure, _, plugin_config: (
                HomeAssistantTelemetryConfigurationBuilder().build(
                    infrastructure, plugin_config
                )
            ),
            create_plugin=lambda config: HomeAssistantTelemetryPlugin(
                check=home_assistant_telemetry_check or HomeAssistantTelemetryCheck(),
                config=config,
            ),
            build_tasks=lambda config, plugin_config, now: (
                build_home_assistant_telemetry_tasks(
                    home_assistant_telemetry_config=config,
                    interval_seconds=plugin_config.interval_seconds,
                    start_at=now,
                )
            ),
            test_plugin=test_home_assistant_telemetry_plugin,
        ),
        PluginSpec(
            identifier="teleinformation",
            display_name="Téléinformation",
            capabilities=("teleinformation.freshness",),
            configuration_model=TeleinformationPluginConfig,
            load_configuration=TeleinformationConfigLoader().load,
            build_config=lambda infrastructure, _, plugin_config: (
                TeleinformationConfigurationBuilder().build(
                    infrastructure, plugin_config
                )
            ),
            create_plugin=lambda config: TeleinformationPlugin(
                check=teleinformation_check or TeleinformationCheck(), config=config
            ),
            build_tasks=lambda config, plugin_config, now: build_teleinformation_tasks(
                teleinformation_config=config,
                interval_seconds=plugin_config.interval_seconds,
                start_at=now,
            ),
            test_plugin=test_teleinformation_plugin,
        ),
        PluginSpec(
            identifier="backup",
            display_name="Sauvegardes",
            capabilities=("backup.run",),
            configuration_model=BackupPluginConfig,
            load_configuration=BackupConfigLoader().load,
            build_config=lambda _, __, plugin_config: (
                BackupConfigurationBuilder().build(plugin_config)
            ),
            create_plugin=lambda config: BackupPlugin(
                config=config, coordinator=backup_coordinator
            ),
            build_tasks=lambda config, _, __: build_backup_tasks(
                backup_config=config,
                schedule_timezone=LOCAL_SCHEDULE_TIMEZONE,
            ),
            test_plugin=lambda plugin: plugin.test(),
            follows_infrastructure=False,
        ),
    )
