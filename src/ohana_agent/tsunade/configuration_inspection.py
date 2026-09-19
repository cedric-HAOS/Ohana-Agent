"""Read selected configuration facts and remote Supervisor state without secrets."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import aiohttp

from ohana_agent.plugins.backup.config import BackupConfig
from ohana_agent.plugins.backup.secrets import resolve_backup_secret


def safe_endpoint(value: object) -> dict:
    if not isinstance(value, str):
        return {"configured": False}
    try:
        parsed = urlsplit(value if "://" in value else "//" + value)
        return {
            "configured": bool(parsed.hostname),
            "scheme": parsed.scheme,
            "host": parsed.hostname,
            "port": parsed.port,
            "credentials_embedded": bool(parsed.username or parsed.password),
        }
    except ValueError:
        return {"configured": True, "valid": False}


def local_mqtt_configuration(plugins) -> dict:
    state = plugins.read("mqtt")
    config = state.configuration
    authentication = config.get("authentication") or {}
    tls = config.get("tls") or {}
    return {
        "source": "Agent: configuration MQTT validée depuis le fichier configuré",
        "enabled": state.enabled,
        "runtime_status": state.status,
        "username_configured": bool(authentication.get("username")),
        "password_configured": bool(authentication.get("password_configured")),
        "tls_enabled": bool(tls.get("enabled")),
        "tls_insecure": bool(tls.get("insecure")),
        "timeout_seconds": config.get("timeout"),
        "retries": config.get("retries"),
        "interval_seconds": config.get("interval_seconds"),
        "qos": config.get("qos"),
        "keepalive_seconds": config.get("keepalive_seconds"),
        "checks": {
            "password_without_username": bool(
                authentication.get("password_configured")
                and not authentication.get("username")
            ),
            "tls_certificate_verification_disabled": bool(tls.get("insecure")),
        },
    }


def serial_paths(hardware: dict) -> set[str]:
    paths = set()

    def visit(value, depth=0):
        if depth > 10 or len(paths) >= 128:
            return
        if isinstance(value, dict):
            for key in ("dev_path", "by_id", "devices", "children"):
                visit(value.get(key), depth + 1)
        elif isinstance(value, list):
            for item in value[:256]:
                visit(item, depth + 1)
        elif isinstance(value, str) and value.startswith("/dev/"):
            paths.add(value[:240])

    visit(hardware)
    return paths


def addon_facts(info: dict, hardware: dict, stats: dict) -> dict:
    options = info.get("options") or {}
    serial = options.get("SERIAL", options.get("serial"))
    serial = serial if isinstance(serial, str) and serial.startswith("/dev/") else None
    selected = {
        key: options[key]
        for key in (
            "TIC_MODE",
            "LOG_LEVEL",
            "EMIT_INTERVAL",
            "OHANA_ENABLED",
            "OHANA_TIMEOUT_MS",
            "require_certificate",
            "log_type",
            "log_dest",
        )
        if isinstance(options.get(key), (str, bool, int, float))
    }
    selected = {
        key: value[:160] if isinstance(value, str) else value
        for key, value in selected.items()
    }
    for key in ("MQTT_URL", "OHANA_URL"):
        if key in options:
            selected[key] = safe_endpoint(options[key])
    for key in ("MQTT_USER", "MQTT_PASSWORD", "OHANA_TOKEN"):
        if key in options:
            selected[key + "_configured"] = bool(options[key])
    return {
        "addon": info.get("slug"),
        "state": info.get("state"),
        "version": info.get("version"),
        "update_available": info.get("update_available"),
        "configuration": selected,
        "mqtt_login_count": len(options.get("logins", [])),
        "custom_configuration_enabled": bool(
            (options.get("customize") or {}).get("active")
        ),
        "serial": {
            "configured_path": serial,
            "listed_by_supervisor": serial in serial_paths(hardware)
            if serial
            else None,
            "uart_access": info.get("uart"),
            "exposed_devices": [
                p
                for p in info.get("devices", [])
                if isinstance(p, str) and p.startswith("/dev/")
            ][:16],
            "limit": "Présence et exposition matérielle uniquement ; un alias "
            "non listé ne prouve pas l’absence. Aucun accès exclusif au port série.",
        },
        "runtime_stats": {
            k: stats.get(k)
            for k in ("cpu_percent", "memory_percent", "memory_usage", "memory_limit")
        },
    }


async def _remote(config: BackupConfig, node_id: str) -> dict:
    target_id = "ha-01" if node_id == "infra-01" else node_id
    target = next((t for t in config.targets if t.id == target_id and t.enabled), None)
    if target is None:
        return {"status": "unavailable", "reason": "Aucun accès Supervisor configuré"}
    token = target.token or resolve_backup_secret(
        config.environment_file, target.token_environment_variable
    )
    if not token:
        return {"status": "unavailable", "reason": "Authentification non configurée"}
    async with asyncio.timeout(8):
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        ) as session:
            url = target.url.rstrip("/").replace("http", "ws", 1) + "/api/websocket"
            async with session.ws_connect(
                url, ssl=None if target.verify_tls else False, max_msg_size=1024 * 1024
            ) as ws:
                if (await ws.receive_json()).get("type") != "auth_required":
                    raise ValueError("Unexpected authentication challenge")
                await ws.send_json({"type": "auth", "access_token": token})
                if (await ws.receive_json()).get("type") != "auth_ok":
                    raise ValueError("Supervisor authentication rejected")
                index = 0

                async def get(endpoint):
                    nonlocal index
                    index += 1
                    await ws.send_json(
                        {
                            "id": index,
                            "type": "supervisor/api",
                            "endpoint": endpoint,
                            "method": "get",
                        }
                    )
                    reply = await ws.receive_json()
                    if not reply.get("success"):
                        return {"unavailable": True}
                    result = reply.get("result")
                    return result if isinstance(result, dict) else {}

                listing = await get("/addons")
                hardware = await get("/hardware/info")
                patterns = {
                    "linky-01": ("teleinfo", "linky"),
                    "zwave-01": ("z-wave js", "zwavejs", "zwave_js"),
                }.get(node_id, ("mosquitto", "mqtt"))
                results = []
                for addon in listing.get("addons", []):
                    slug = addon.get("slug", "")
                    if not slug or not all(c.isalnum() or c in "_-" for c in slug):
                        continue
                    if not any(
                        p in (slug + " " + addon.get("name", "")).lower()
                        for p in patterns
                    ):
                        continue
                    info = await get(f"/addons/{slug}/info")
                    stats = await get(f"/addons/{slug}/stats")
                    results.append(addon_facts(info, hardware, stats))
                    if len(results) == 2:
                        break
                core = await get("/core/info")
                return {
                    "origin": target_id + " / Supervisor",
                    "transport": "authenticated GET",
                    "addons": results,
                    "addon_selection": {
                        "patterns": list(patterns),
                        "status": (
                            "unavailable"
                            if listing.get("unavailable")
                            else "matched"
                            if results
                            else "no_match"
                        ),
                        "limit": "Une absence de correspondance ne prouve pas "
                        "que le service est arrêté ou absent de la machine.",
                    },
                    "hardware_available": not hardware.get("unavailable"),
                    "core": {
                        k: core.get(k) for k in ("version", "state", "update_available")
                    },
                    "limits": "Options déclarées et état Supervisor, sans commandes "
                    "dans le conteneur ni lecture de fichiers arbitraires.",
                }


def inspect_configuration(plugins, config: BackupConfig, node_id: str) -> dict:
    try:
        local = local_mqtt_configuration(plugins)
    except Exception as error:
        local = {"status": "unavailable", "error": type(error).__name__}
    try:
        remote = asyncio.run(_remote(config, node_id))
    except Exception as error:
        remote = {"status": "unavailable", "error": type(error).__name__}
    return {"inspection_version": 2, "agent_mqtt": local, "remote": remote}
