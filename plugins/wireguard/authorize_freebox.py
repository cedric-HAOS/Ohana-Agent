"""Authorize Ohana-Agent against the local Freebox OS API."""

from __future__ import annotations

import argparse
import socket
import time
from collections.abc import Sequence
from pathlib import Path

import yaml

from plugins.wireguard.wireguard_client import FreeboxWireGuardClient

DEFAULT_FREEBOX_URL = "http://mafreebox.freebox.fr"
DEFAULT_CONFIG_PATH = Path("/etc/ohana-agent/plugins/wireguard.yaml")
DEFAULT_APPROVAL_TIMEOUT = 90.0
DEFAULT_POLL_INTERVAL = 2.0


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Request a Freebox OS application token and store it in the "
            "WireGuard plugin configuration."
        )
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_FREEBOX_URL,
        help="Local Freebox URL, for example http://192.168.1.1.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="WireGuard plugin YAML configuration.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_APPROVAL_TIMEOUT,
        help="Maximum approval wait in seconds.",
    )
    return parser.parse_args(argv)


def authorize_freebox(
    *,
    base_url: str,
    config_path: Path,
    approval_timeout: float,
    client: FreeboxWireGuardClient | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> int:
    """Request Freebox approval and persist the resulting application token."""
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    app_id = str(payload.get("app_id", "fr.ohana.agent"))
    app_version = str(payload.get("app_version", "1.7.4"))
    verify_tls = bool(payload.get("verify_tls", False))
    freebox_client = client or FreeboxWireGuardClient()
    app_token, track_id, api_root = freebox_client.request_authorization(
        base_url,
        app_id=app_id,
        app_name="Ohana-Agent",
        app_version=app_version,
        device_name=socket.gethostname(),
        verify_tls=verify_tls,
    )

    print("Demande envoyée à la Freebox.")
    print("Validez maintenant l'autorisation sur l'écran de la Freebox.")
    deadline = time.monotonic() + approval_timeout

    while time.monotonic() < deadline:
        status = freebox_client.authorization_status(
            api_root,
            track_id,
            verify_tls=verify_tls,
        )

        if status == "granted":
            payload["app_token"] = app_token
            config_path.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            print(f"Autorisation accordée. Token enregistré dans {config_path}.")
            return 0

        if status in {"denied", "timeout"}:
            print(f"Autorisation non accordée : {status}.")
            return 1

        time.sleep(poll_interval)

    print("Délai dépassé avant validation sur la Freebox.")
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the installed Freebox authorization command."""
    arguments = parse_arguments(argv)
    return authorize_freebox(
        base_url=arguments.url,
        config_path=arguments.config,
        approval_timeout=arguments.timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
