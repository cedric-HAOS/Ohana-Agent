"""Command-line entry point for Ohana-Agent."""

from __future__ import annotations

import argparse
import logging
import signal
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from types import FrameType

from bootstrap import build_production_agent
from production_agent import ProductionAgent


def get_application_version() -> str:
    """Return the installed Ohana-Agent package version."""
    try:
        return package_version("ohana-agent")
    except PackageNotFoundError:
        return "unknown"


def parse_arguments() -> argparse.Namespace:
    """Parse Ohana-Agent command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="ohana-agent",
        description="Run Ohana-Agent.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ohana-agent {get_application_version()}",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/shikamaru.yaml"),
        help="Application configuration file.",
    )
    parser.add_argument(
        "--infrastructure",
        type=Path,
        default=Path("config/infrastructure.yaml"),
        help="Infrastructure configuration file.",
    )
    parser.add_argument(
        "--dns-config",
        type=Path,
        default=Path("config/plugins/dns.yaml"),
        help="DNS plugin configuration file.",
    )
    parser.add_argument(
        "--ntp-config",
        type=Path,
        default=Path("config/plugins/ntp.yaml"),
        help="NTP plugin configuration file.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=[
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ],
        help="Console logging level.",
    )

    return parser.parse_args()


def configure_logging(level: str) -> None:
    """Configure console logging for systemd and manual runs."""
    normalized_level = level.upper()

    if normalized_level not in {
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    }:
        raise ValueError(f"Unsupported logging level: {level!r}.")

    logging.basicConfig(
        level=getattr(
            logging,
            normalized_level,
        ),
        format=("%(asctime)s %(levelname)s %(name)s — %(message)s"),
        force=True,
    )


def install_signal_handlers(
    agent: ProductionAgent,
) -> None:
    """Stop the agent cleanly on SIGINT or SIGTERM."""

    def request_stop(
        signum: int,
        frame: FrameType | None,
    ) -> None:
        del signum, frame
        agent.request_stop()

    signal.signal(
        signal.SIGINT,
        request_stop,
    )
    signal.signal(
        signal.SIGTERM,
        request_stop,
    )


def main() -> int:
    """Build and run Ohana-Agent."""
    arguments = parse_arguments()

    configure_logging(arguments.log_level)

    agent = build_production_agent(
        application_config_path=arguments.config,
        infrastructure_config_path=arguments.infrastructure,
        dns_config_path=arguments.dns_config,
        ntp_config_path=arguments.ntp_config,
    )

    install_signal_handlers(agent)
    agent.run()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
