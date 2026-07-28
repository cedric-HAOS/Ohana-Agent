import logging
import signal
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

from main import (
    configure_logging,
    get_application_version,
    install_signal_handlers,
    parse_arguments,
)


@dataclass
class FakeProductionAgent:
    """Minimal production agent used by signal tests."""

    stop_requested: bool = False

    def request_stop(self) -> None:
        self.stop_requested = True


def test_parse_arguments_uses_default_configuration_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["ohana-agent"],
    )

    arguments = parse_arguments()

    assert arguments.config == Path("config/shikamaru.yaml")
    assert arguments.infrastructure == Path("config/infrastructure.yaml")
    assert arguments.dhcp_config == Path("config/plugins/dhcp.yaml")
    assert arguments.dns_config == Path("config/plugins/dns.yaml")
    assert arguments.ntp_config == Path("config/plugins/ntp.yaml")
    assert arguments.mqtt_config == Path("config/plugins/mqtt.yaml")
    assert arguments.network_config == Path("config/plugins/network.yaml")
    assert arguments.zwave_config == Path("config/plugins/zwave.yaml")
    assert arguments.wireguard_config == Path("config/plugins/wireguard.yaml")
    assert arguments.shelly_telemetry_config == Path(
        "config/plugins/shelly-telemetry.yaml"
    )
    assert arguments.log_level == "INFO"


def test_parse_arguments_accepts_custom_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ohana-agent",
            "--config",
            "custom/application.yaml",
            "--infrastructure",
            "custom/infrastructure.yaml",
            "--dhcp-config",
            "custom/dhcp.yaml",
            "--dns-config",
            "custom/dns.yaml",
            "--ntp-config",
            "custom/ntp.yaml",
            "--mqtt-config",
            "custom/mqtt.yaml",
            "--network-config",
            "custom/network.yaml",
            "--zwave-config",
            "custom/zwave.yaml",
            "--wireguard-config",
            "custom/wireguard.yaml",
            "--shelly-telemetry-config",
            "custom/shelly-telemetry.yaml",
            "--log-level",
            "DEBUG",
        ],
    )

    arguments = parse_arguments()

    assert arguments.config == Path("custom/application.yaml")
    assert arguments.infrastructure == Path("custom/infrastructure.yaml")
    assert arguments.dhcp_config == Path("custom/dhcp.yaml")
    assert arguments.dns_config == Path("custom/dns.yaml")
    assert arguments.ntp_config == Path("custom/ntp.yaml")
    assert arguments.mqtt_config == Path("custom/mqtt.yaml")
    assert arguments.network_config == Path("custom/network.yaml")
    assert arguments.zwave_config == Path("custom/zwave.yaml")
    assert arguments.wireguard_config == Path("custom/wireguard.yaml")
    assert arguments.shelly_telemetry_config == Path("custom/shelly-telemetry.yaml")
    assert arguments.log_level == "DEBUG"


@pytest.mark.parametrize(
    "level",
    [
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ],
)
def test_configure_logging_accepts_known_level(
    level: str,
) -> None:
    configure_logging(level)

    assert logging.getLogger().level == getattr(
        logging,
        level,
    )


def test_configure_logging_accepts_lowercase_level() -> None:
    configure_logging("debug")

    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_rejects_unknown_level() -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported logging level",
    ):
        configure_logging("TRACE")


def test_parse_arguments_rejects_invalid_log_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ohana-agent",
            "--log-level",
            "TRACE",
        ],
    )

    with pytest.raises(SystemExit):
        parse_arguments()


def test_install_signal_handlers_registers_sigint_and_sigterm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered_handlers: dict[
        signal.Signals,
        object,
    ] = {}

    def fake_signal(
        signal_number: signal.Signals,
        handler: object,
    ) -> None:
        registered_handlers[signal_number] = handler

    monkeypatch.setattr(
        signal,
        "signal",
        fake_signal,
    )

    agent = FakeProductionAgent()

    install_signal_handlers(agent)  # type: ignore[arg-type]

    assert signal.SIGINT in registered_handlers
    assert signal.SIGTERM in registered_handlers


def test_signal_handler_requests_agent_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered_handlers: dict[
        signal.Signals,
        object,
    ] = {}

    def fake_signal(
        signal_number: signal.Signals,
        handler: object,
    ) -> None:
        registered_handlers[signal_number] = handler

    monkeypatch.setattr(
        signal,
        "signal",
        fake_signal,
    )

    agent = FakeProductionAgent()

    install_signal_handlers(agent)  # type: ignore[arg-type]

    handler = registered_handlers[signal.SIGTERM]

    assert callable(handler)

    handler(  # type: ignore[operator]
        signal.SIGTERM,
        None,
    )

    assert agent.stop_requested is True


def test_main_builds_and_runs_production_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    class FakeAgent:
        def run(self) -> None:
            calls.append("run")

        def request_stop(self) -> None:
            pass

    fake_agent = FakeAgent()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ohana-agent",
            "--config",
            "custom/application.yaml",
            "--infrastructure",
            "custom/infrastructure.yaml",
            "--dhcp-config",
            "custom/dhcp.yaml",
            "--dns-config",
            "custom/dns.yaml",
            "--ntp-config",
            "custom/ntp.yaml",
            "--mqtt-config",
            "custom/mqtt.yaml",
            "--network-config",
            "custom/network.yaml",
            "--zwave-config",
            "custom/zwave.yaml",
            "--wireguard-config",
            "custom/wireguard.yaml",
            "--shelly-telemetry-config",
            "custom/shelly-telemetry.yaml",
            "--log-level",
            "DEBUG",
        ],
    )

    def fake_configure_logging(level: str) -> None:
        calls.append(
            (
                "configure_logging",
                level,
            )
        )

    def fake_build_production_agent(
        *,
        application_config_path: Path,
        infrastructure_config_path: Path,
        dhcp_config_path: Path,
        dns_config_path: Path,
        ntp_config_path: Path,
        mqtt_config_path: Path,
        network_config_path: Path,
        zwave_config_path: Path,
        wireguard_config_path: Path,
        shelly_telemetry_config_path: Path,
    ) -> FakeAgent:
        calls.append(
            (
                "build_production_agent",
                application_config_path,
                infrastructure_config_path,
                dhcp_config_path,
                dns_config_path,
                ntp_config_path,
                mqtt_config_path,
                network_config_path,
                zwave_config_path,
                wireguard_config_path,
                shelly_telemetry_config_path,
            )
        )
        return fake_agent

    def fake_install_signal_handlers(
        agent: object,
    ) -> None:
        calls.append(
            (
                "install_signal_handlers",
                agent,
            )
        )

    monkeypatch.setattr(
        "main.configure_logging",
        fake_configure_logging,
    )
    monkeypatch.setattr(
        "main.build_production_agent",
        fake_build_production_agent,
    )
    monkeypatch.setattr(
        "main.install_signal_handlers",
        fake_install_signal_handlers,
    )

    from main import main

    result = main()

    assert result == 0
    assert calls == [
        (
            "configure_logging",
            "DEBUG",
        ),
        (
            "build_production_agent",
            Path("custom/application.yaml"),
            Path("custom/infrastructure.yaml"),
            Path("custom/dhcp.yaml"),
            Path("custom/dns.yaml"),
            Path("custom/ntp.yaml"),
            Path("custom/mqtt.yaml"),
            Path("custom/network.yaml"),
            Path("custom/zwave.yaml"),
            Path("custom/wireguard.yaml"),
            Path("custom/shelly-telemetry.yaml"),
        ),
        (
            "install_signal_handlers",
            fake_agent,
        ),
        "run",
    ]


def test_get_application_version_returns_installed_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "main.package_version",
        lambda package_name: "1.0.0",
    )

    assert get_application_version() == "1.0.0"


def test_get_application_version_returns_unknown_when_package_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_package_not_found(
        package_name: str,
    ) -> str:
        raise PackageNotFoundError(package_name)

    monkeypatch.setattr(
        "main.package_version",
        raise_package_not_found,
    )

    assert get_application_version() == "unknown"


def test_parse_arguments_displays_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "main.get_application_version",
        lambda: "1.0.0",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ohana-agent",
            "--version",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        parse_arguments()

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == ("ohana-agent 1.0.0")


def test_parse_arguments_accepts_linux_configuration_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept the absolute paths used by the systemd service."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ohana-agent",
            "--config",
            "/etc/ohana-agent/shikamaru.yaml",
            "--infrastructure",
            "/etc/ohana-agent/infrastructure.yaml",
            "--dhcp-config",
            "/etc/ohana-agent/plugins/dhcp.yaml",
            "--dns-config",
            "/etc/ohana-agent/plugins/dns.yaml",
            "--ntp-config",
            "/etc/ohana-agent/plugins/ntp.yaml",
            "--mqtt-config",
            "/etc/ohana-agent/plugins/mqtt.yaml",
            "--network-config",
            "/etc/ohana-agent/plugins/network.yaml",
            "--zwave-config",
            "/etc/ohana-agent/plugins/zwave.yaml",
            "--wireguard-config",
            "/etc/ohana-agent/plugins/wireguard.yaml",
            "--shelly-telemetry-config",
            "/etc/ohana-agent/plugins/shelly-telemetry.yaml",
        ],
    )

    arguments = parse_arguments()

    assert arguments.config == Path(
        "/etc/ohana-agent/shikamaru.yaml",
    )
    assert arguments.infrastructure == Path(
        "/etc/ohana-agent/infrastructure.yaml",
    )
    assert arguments.dhcp_config == Path(
        "/etc/ohana-agent/plugins/dhcp.yaml",
    )
    assert arguments.dns_config == Path(
        "/etc/ohana-agent/plugins/dns.yaml",
    )
    assert arguments.ntp_config == Path(
        "/etc/ohana-agent/plugins/ntp.yaml",
    )
    assert arguments.mqtt_config == Path(
        "/etc/ohana-agent/plugins/mqtt.yaml",
    )
    assert arguments.network_config == Path(
        "/etc/ohana-agent/plugins/network.yaml",
    )
    assert arguments.zwave_config == Path(
        "/etc/ohana-agent/plugins/zwave.yaml",
    )
    assert arguments.wireguard_config == Path(
        "/etc/ohana-agent/plugins/wireguard.yaml",
    )
    assert arguments.shelly_telemetry_config == Path(
        "/etc/ohana-agent/plugins/shelly-telemetry.yaml",
    )
