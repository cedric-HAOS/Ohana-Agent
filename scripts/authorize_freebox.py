"""Authorize Ohana-Agent against the local Freebox OS API."""

from __future__ import annotations

import argparse
import socket
import time
from pathlib import Path

import yaml

from plugins.wireguard.wireguard_client import FreeboxWireGuardClient


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Request a Freebox OS application token and store it in the "
            "WireGuard plugin configuration."
        )
    )
    parser.add_argument(
        "--url",
        default="http://mafreebox.freebox.fr",
        help="Local Freebox URL, for example http://192.168.1.1.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/plugins/wireguard.yaml"),
        help="WireGuard plugin YAML configuration.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="Maximum approval wait in seconds.",
    )
    return parser.parse_args()


def main() -> int:
    """Request authorization, wait for approval and persist the token."""
    arguments = parse_arguments()
    config_path = arguments.config
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    app_id = str(payload.get("app_id", "fr.ohana.agent"))
    app_version = str(payload.get("app_version", "1.7.0"))
    verify_tls = bool(payload.get("verify_tls", False))
    client = FreeboxWireGuardClient()
    app_token, track_id, api_root = client.request_authorization(
        arguments.url,
        app_id=app_id,
        app_name="Ohana-Agent",
        app_version=app_version,
        device_name=socket.gethostname(),
        verify_tls=verify_tls,
    )

    print("Demande envoyée à la Freebox.")
    print("Validez maintenant l'autorisation sur l'écran de la Freebox.")
    deadline = time.monotonic() + arguments.timeout

    while time.monotonic() < deadline:
        status = client.authorization_status(
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

        time.sleep(2)

    print("Délai dépassé avant validation sur la Freebox.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
