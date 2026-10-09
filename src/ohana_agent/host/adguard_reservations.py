"""Publish reserved DHCP names before the existing AdGuard replication cycle."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from ipaddress import IPv4Address
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import httpx
import yaml

from ohana_agent.configuration.administration import DHCPAdministrationConfig
from ohana_agent.host.dhcp import DnsmasqDHCPRepository

DOMAIN = "ohana.lan"
CONFIG_PATH = Path("/etc/ohana-agent/adguardhome-sync.yaml")
STATE_PATH = Path("/etc/ohana-agent/adguard-reservations-state.json")
Rewrite = tuple[str, str]


def read_reserved_names(config: DHCPAdministrationConfig) -> set[Rewrite]:
    """Use the administration reader, never the dynamic lease database."""
    paths = {
        "infrastructure": config.infrastructure_reservations_path,
        "servers": config.server_reservations_path,
        "network": config.network_reservations_path,
        "home_automation": config.home_automation_reservations_path,
        "critical": config.critical_reservations_path,
    }
    for path in (config.main_config_path, *paths.values()):
        if not path.is_file():
            raise ValueError(f"Missing DHCP configuration: {path}")
    repository = DnsmasqDHCPRepository(
        main_config_path=config.main_config_path,
        reservation_paths=paths,
        leases_path=config.leases_path,
    )
    configuration = repository.read_configuration()
    if configuration.settings.domain != DOMAIN:
        raise ValueError(f"DHCP domain must be {DOMAIN}")
    names: set[Rewrite] = set()
    for reservation in configuration.reservations:
        hostname = reservation.hostname
        if hostname.endswith(f".{DOMAIN}"):
            name = hostname
        elif "." not in hostname:
            name = f"{hostname}.{DOMAIN}"
        else:
            raise ValueError(f"Reservation outside {DOMAIN}: {hostname}")
        if len(name) > 253 or any(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
            for label in name.split(".")
        ):
            raise ValueError(f"Invalid reserved DNS name: {name}")
        names.add((name, str(reservation.address)))
    if len({name for name, _ in names}) != len(names):
        raise ValueError("Duplicate reserved DNS name")
    return names


def read_state(path: Path) -> set[Rewrite]:
    if not path.exists():
        return set()
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("Invalid reservation synchronization state")
    entries = document.get("rewrites")
    if not isinstance(entries, list):
        raise ValueError("Invalid managed rewrite list")
    result = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid managed rewrite")
        name, answer = entry.get("domain"), entry.get("answer")
        if not isinstance(name, str) or not name.endswith(f".{DOMAIN}"):
            raise ValueError("Managed rewrite outside the local domain")
        result.add((name, str(IPv4Address(answer))))
    return result


def write_state(path: Path, entries: set[Rewrite]) -> None:
    """Save ownership atomically, including pending operations for retry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            # The service's primary group is ohana-agent, which must read this
            # file when building the encrypted cloud backup.
            os.chmod(temporary, 0o640)
            json.dump(
                {
                    "schema_version": 1,
                    "rewrites": [
                        {"domain": name, "answer": answer}
                        for name, answer in sorted(entries)
                    ],
                },
                stream,
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class AdGuardAPI:
    """Small bounded client for the official rewrite API."""

    def __init__(self, instance: dict[str, Any]) -> None:
        url = instance.get("url")
        username, password = instance.get("username"), instance.get("password")
        if not all(
            isinstance(value, str) and value for value in (url, username, password)
        ):
            raise ValueError("AdGuard URL and credentials are required")
        self.base = (
            url.rstrip("/") + "/" + instance.get("apiPath", "/control").strip("/")
        )
        self.client = httpx.Client(
            auth=(username, password),
            timeout=10.0,
            trust_env=False,
        )

    def close(self) -> None:
        self.client.close()

    def entries(self) -> set[Rewrite]:
        response = self.client.get(f"{self.base}/rewrite/list")
        response.raise_for_status()
        entries = response.json()
        if not isinstance(entries, list) or not all(
            isinstance(entry, dict)
            and isinstance(entry.get("domain"), str)
            and isinstance(entry.get("answer"), str)
            for entry in entries
        ):
            raise ValueError("Invalid AdGuard rewrite response")
        return {
            (entry["domain"].lower().rstrip("."), entry["answer"]) for entry in entries
        }

    def change(self, action: str, entry: Rewrite) -> None:
        response = self.client.post(
            f"{self.base}/rewrite/{action}",
            json={"domain": entry[0], "answer": entry[1]},
        )
        response.raise_for_status()


def reconcile(
    desired: set[Rewrite], api: AdGuardAPI, state_path: Path, *, dry_run: bool = False
) -> tuple[int, int]:
    """Only remove exact entries owned by a previous successful or pending run."""
    previous = read_state(state_path)
    current = api.entries()
    desired_domains = {name for name, _ in desired}
    conflicts = {
        name
        for name, answer in current
        if name in desired_domains and (name, answer) not in desired | previous
    }
    if conflicts:
        raise ValueError(
            "Conflicting manual DNS rewrites: " + ", ".join(sorted(conflicts))
        )
    additions = desired - current
    removals = (previous - desired) & current
    if dry_run:
        return len(additions), len(removals)
    # Journal intent before contacting AdGuard: retry handles an ambiguous timeout
    # or interruption after the remote mutation but before local confirmation.
    pending = previous | desired
    if pending != previous:
        write_state(state_path, pending)
    for entry in sorted(additions):
        api.change("add", entry)
    for entry in sorted(removals):
        api.change("delete", entry)
    verified = api.entries()
    if not desired <= verified or removals & verified:
        raise ValueError("AdGuard did not confirm reserved DNS rewrites")
    if desired != pending:
        write_state(state_path, desired)
    return len(additions), len(removals)


def load_config(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Invalid AdGuard synchronization configuration")
    features = document.get("features", {})
    if features.get("dns", {}).get("rewrites") is not True or any(
        features.get("dhcp", {}).get(key) is not False
        for key in ("serverConfig", "staticLeases")
    ):
        raise ValueError("DNS rewrites must be enabled and DHCP replication disabled")
    if not all(isinstance(document.get(key), dict) for key in ("origin", "replica")):
        raise ValueError("One AdGuard origin and replica are required")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--verify-replica", action="store_true")
    arguments = parser.parse_args()
    clients: list[AdGuardAPI] = []
    try:
        document = load_config(arguments.config)
        origin = AdGuardAPI(document["origin"])
        clients.append(origin)
        if arguments.verify_replica:
            replica = AdGuardAPI(document["replica"])
            clients.append(replica)
            if origin.entries() != replica.entries():
                raise ValueError("AdGuard replica rewrites differ from origin")
            print("AdGuard replica DNS rewrites verified")
        else:
            desired = read_reserved_names(DHCPAdministrationConfig())
            added, removed = reconcile(
                desired,
                origin,
                arguments.state,
                dry_run=arguments.dry_run,
            )
            label = "Planned" if arguments.dry_run else "Verified"
            print(
                f"{label}: {len(desired)} reserved names, "
                f"{added} additions, {removed} removals"
            )
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        httpx.HTTPError,
        yaml.YAMLError,
    ):
        # Never log the configuration, credentials, response bodies, or auth URLs.
        print(
            "Reservation DNS synchronization failed; "
            "check configuration and AdGuard access",
            file=sys.stderr,
        )
        return 1
    finally:
        for client in clients:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
