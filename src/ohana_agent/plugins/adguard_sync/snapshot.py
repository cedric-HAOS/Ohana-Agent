"""Compare replicated settings, never exporting their values or credentials.

API contract: AdguardTeam/AdGuardHome openapi/openapi.yaml.
Replication contract: bakito/adguardhome-sync internal/sync/action-general.go.
"""

import json
from ipaddress import ip_address
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml

from ohana_agent.configuration.adguard_sync import AdGuardSyncPluginConfig


def _select(document: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(document, dict) or any(key not in document for key in fields):
        raise ValueError("Incomplete AdGuard response")
    expected_types = {
        "enabled": bool,
        "use_global_settings": bool,
        "protection_enabled": bool,
        "domain": str,
        "answer": str,
        "name": str,
        "url": str,
        "language": str,
        "theme": str,
        "clients": list,
        "ids": list,
        "upstream_dns": list,
        "allowed_clients": list,
        "disallowed_clients": list,
        "blocked_hosts": list,
        "schedule": dict,
    }
    if any(
        key in expected_types and not isinstance(document[key], expected_types[key])
        for key in fields
    ):
        raise ValueError("Invalid AdGuard response field")
    return {key: document[key] for key in fields}


def _response_list(document: Any, field: str) -> list[Any]:
    """AdGuard encodes an empty Go slice as null on some API versions."""
    if not isinstance(document, dict) or field not in document:
        raise ValueError("Missing AdGuard list")
    value = document[field]
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Invalid AdGuard list")
    return value


def _unordered(items: Any) -> list[Any]:
    if not isinstance(items, list):
        raise ValueError("Expected an AdGuard list")
    return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))


def _features(document: dict[str, Any]) -> dict[str, Any]:
    flags: dict[str, Any] = {
        "dns": {"accessLists": True, "serverConfig": True, "rewrites": True},
        "dhcp": {"serverConfig": True, "staticLeases": True},
        "generalSettings": True,
        "clientSettings": True,
        "services": True,
        "filters": {"blacklist": True, "whitelist": True, "userRules": True},
        "queryLogConfig": True,
        "statsConfig": True,
        "theme": True,
        "protectionStatus": False,
        "tlsConfig": False,
    }
    overrides = document.get("features", {})
    if not isinstance(overrides, dict):
        raise ValueError("Invalid replication features")
    for key, value in overrides.items():
        if key not in flags:
            raise ValueError("Unsupported replication feature")
        if isinstance(flags[key], dict):
            if key == "filters" and isinstance(value, bool):
                flags[key] = dict.fromkeys(flags[key], value)
            else:
                if not isinstance(value, dict) or set(value) - set(flags[key]):
                    raise ValueError("Invalid replication feature group")
                if key == "filters":
                    flags[key] = dict.fromkeys(flags[key], False)
                flags[key].update(value)
                if any(not isinstance(flag, bool) for flag in flags[key].values()):
                    raise ValueError("Replication flags must be booleans")
        elif isinstance(value, bool):
            flags[key] = value
        else:
            raise ValueError("Replication flags must be booleans")
    if any(flags["dhcp"].values()) or flags["tlsConfig"]:
        raise ValueError("DHCP and TLS replication are outside this observer's scope")
    return flags


class AdGuardSnapshotProbe:
    def _configuration(
        self, settings: AdGuardSyncPluginConfig
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with settings.sync_config_path.open("rb") as source:
            raw = source.read(65537)
        if len(raw) > 65536:
            raise ValueError("Synchronization configuration is too large")
        document = yaml.safe_load(raw)
        if not isinstance(document, dict) or document.get("replicas"):
            raise ValueError("One origin and one replica are required")
        flags = _features(document)
        instances = [document["origin"], document["replica"]]
        hosts = [self._instance(instance)[1] for instance in instances]
        if hosts[0] == hosts[1]:
            raise ValueError("Two distinct DNS server addresses are required")
        if any(instance.get("features") is not None for instance in instances):
            raise ValueError("Per-instance feature overrides are unsupported")
        return flags, instances

    def validate_access(self, settings: AdGuardSyncPluginConfig) -> None:
        """Read both APIs before the first cycle creates local DNS rewrites."""
        flags, instances = self._configuration(settings)
        deadline = monotonic() + 25
        for instance in instances:
            if not self._snapshot(instance, flags, settings.timeout, deadline):
                raise ValueError("No replicated sections selected")

    def inspect(self, settings: AdGuardSyncPluginConfig) -> dict[str, Any]:
        flags, instances = self._configuration(settings)
        deadline = monotonic() + 25
        snapshots = [
            self._snapshot(instance, flags, settings.timeout, deadline)
            for instance in instances
        ]
        origin_dns = snapshots[0].get("dns.server_config", {})
        if origin_dns.get("use_private_ptr_resolvers") and not origin_dns.get(
            "local_ptr_upstreams"
        ):
            # adguardhome-sync deliberately disables this on the replica.
            origin_dns["use_private_ptr_resolvers"] = False
        if not snapshots[0]:
            raise ValueError("No replicated sections selected")
        differences = [
            key for key in snapshots[0] if snapshots[0][key] != snapshots[1][key]
        ]
        return {
            "checked_sections": list(snapshots[0]),
            "different_sections": differences,
        }

    @staticmethod
    def _instance(instance: Any) -> tuple[str, str, tuple[str, str]]:
        if not isinstance(instance, dict):
            raise ValueError("Invalid AdGuard instance")
        url = instance.get("url")
        username, password = instance.get("username"), instance.get("password")
        if not all(
            isinstance(value, str) and value for value in (url, username, password)
        ):
            raise ValueError("AdGuard URL and credentials are required")
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Invalid AdGuard URL")
        if instance.get("insecureSkipVerify"):
            raise ValueError("TLS certificate verification is required")
        host = str(ip_address(parsed.hostname or ""))
        api_path = instance.get("apiPath", "/control")
        if not isinstance(api_path, str) or "?" in api_path or "#" in api_path:
            raise ValueError("Invalid AdGuard API path")
        return url.rstrip("/") + "/" + api_path.strip("/"), host, (username, password)

    def _snapshot(
        self,
        instance: dict[str, Any],
        flags: dict[str, Any],
        timeout: float,
        deadline: float,
    ) -> dict[str, Any]:
        base, _, auth = self._instance(instance)
        sections: dict[str, Any] = {}
        with httpx.Client(auth=auth, timeout=timeout, trust_env=False) as client:

            def get(path: str) -> Any:
                remaining = min(timeout, deadline - monotonic())
                if remaining <= 0:
                    raise ValueError("AdGuard probe deadline exceeded")
                # Stream with a hard size bound; no response data reaches metadata.
                with client.stream(
                    "GET", base + "/" + path, timeout=remaining
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 2_000_000 or monotonic() > deadline:
                            raise ValueError("AdGuard response exceeds probe limits")
                return json.loads(body)

            if flags["dns"]["rewrites"]:
                entries = get("rewrite/list")
                if not isinstance(entries, list):
                    raise ValueError("Invalid rewrite list")
                sections["dns.rewrites"] = _unordered(
                    [
                        {
                            **_select(entry, ("domain", "answer")),
                            "enabled": entry.get("enabled", True),
                        }
                        for entry in entries
                    ]
                )
                sections["dns.rewrite_settings"] = _select(
                    get("rewrite/settings"), ("enabled",)
                )
            if flags["dns"]["accessLists"]:
                access = _select(
                    get("access/list"),
                    (
                        "allowed_clients",
                        "disallowed_clients",
                        "blocked_hosts",
                    ),
                )
                sections["dns.access_lists"] = {
                    key: _unordered(value) for key, value in access.items()
                }
            if flags["dns"]["serverConfig"]:
                dns_config = get("dns_info")
                _select(dns_config, ("upstream_dns",))
                # This field is discovered separately on each host, never replicated.
                sections["dns.server_config"] = {
                    key: value
                    for key, value in dns_config.items()
                    if key != "default_local_ptr_upstreams"
                }
                normalized_dns = sections["dns.server_config"]
                for field in ("upstream_dns", "bootstrap_dns", "local_ptr_upstreams"):
                    if field in normalized_dns and normalized_dns[field] is not None:
                        normalized_dns[field] = _unordered(normalized_dns[field])
                if not normalized_dns.get("edns_cs_use_custom"):
                    normalized_dns.pop("edns_cs_custom_ip", None)
            filters = flags["filters"]
            if any(filters.values()):
                data = get("filtering/status")
                sections["filters.settings"] = _select(data, ("enabled", "interval"))
                for flag, field in (
                    ("blacklist", "filters"),
                    ("whitelist", "whitelist_filters"),
                ):
                    if filters[flag]:
                        sections[f"filters.{flag}"] = _unordered(
                            [
                                _select(item, ("url", "name", "enabled"))
                                for item in _response_list(data, field)
                            ]
                        )
                if filters["userRules"]:
                    sections["filters.user_rules"] = _response_list(data, "user_rules")
            if flags["clientSettings"]:
                data = _response_list(get("clients"), "clients")
                clients = []
                for item in data:
                    _select(item, ("name", "ids", "use_global_settings"))
                    clients.append(
                        {
                            key: _unordered(value)
                            if key in {"ids", "tags", "blocked_services", "upstreams"}
                            else value
                            for key, value in item.items()
                            if key
                            not in {"whois_info", "disallowed", "disallowed_rule"}
                        }
                    )
                sections["clients"] = _unordered(clients)
            if flags["services"]:
                sections["blocked_services"] = _select(
                    get("blocked_services/get"), ("ids", "schedule")
                )
                sections["blocked_services"]["ids"] = _unordered(
                    sections["blocked_services"]["ids"]
                )
            if flags["generalSettings"]:
                profile_fields = (
                    ("language", "theme") if flags["theme"] else ("language",)
                )
                sections["profile"] = _select(get("profile"), profile_fields)
                for section in ("parental", "safebrowsing"):
                    sections[section] = _select(get(section + "/status"), ("enabled",))
                sections["safesearch"] = get("safesearch/status")
                _select(sections["safesearch"], ("enabled",))
                if flags["protectionStatus"]:
                    sections["protection"] = _select(
                        get("status"), ("protection_enabled",)
                    )
            for flag, path in (
                ("queryLogConfig", "querylog/config"),
                ("statsConfig", "stats/config"),
            ):
                if flags[flag]:
                    sections[flag] = get(path)
                    _select(sections[flag], ("enabled",))
        return sections
