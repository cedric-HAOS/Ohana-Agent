"""
Ohana-Agent

Component:
    Configuration enums

Description:
    Defines shared enums used by configuration models.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

from enum import StrEnum


class Environment(StrEnum):
    """Available runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Available logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class TopologyDeviceKind(StrEnum):
    """Kinds of devices supported by the Vision topology contract."""

    INTERNET = "internet"
    ROUTER = "router"
    SWITCH = "switch"
    ACCESS_POINT = "access_point"
    SERVER = "server"
    RASPBERRY_PI = "raspberry_pi"
    HOME_ASSISTANT = "home_assistant"
    CAMERA = "camera"
    SMART_DEVICE = "smart_device"
    ZWAVE_MODULE = "zwave_module"
    SOLAR = "solar"
    COMPUTER = "computer"
    STORAGE = "storage"
    OTHER = "other"


class TopologyLinkKind(StrEnum):
    """Kinds of links supported by the Vision topology contract."""

    ETHERNET = "ethernet"
    WIFI = "wifi"
    WIREGUARD = "wireguard"
    ZIGBEE = "zigbee"
    ZWAVE = "zwave"
    MQTT = "mqtt"
    USB = "usb"
    SERIAL = "serial"
    LOGICAL = "logical"
    OTHER = "other"


class TopologyLinkDirection(StrEnum):
    """Directions supported by topology links."""

    UNDIRECTED = "undirected"
    SOURCE_TO_TARGET = "source_to_target"
    BIDIRECTIONAL = "bidirectional"


class TopologyLayoutKind(StrEnum):
    """Kinds of layouts supported by the Vision topology contract."""

    PHYSICAL = "physical"
    LOGICAL = "logical"
    SERVICES = "services"
    CUSTOM = "custom"
