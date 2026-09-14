"""Bounded read-only probes of declared endpoints, from the Agent host."""

from __future__ import annotations

import http.client
import socket
from collections.abc import Callable
from datetime import datetime
from queue import Empty, Queue
from threading import BoundedSemaphore, Thread
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ohana_agent.configuration.infrastructure import InfrastructureConfig

_SLOTS = BoundedSemaphore(8)


def probe_endpoint(host: str, port: int | None, scheme: str | None) -> dict:
    """No shell, credentials, response bodies, redirects or arbitrary URL paths."""
    result: dict = {"dns": "pending"}
    try:
        addresses = socket.getaddrinfo(host, port or 0, type=socket.SOCK_STREAM)
        result["dns"] = "OK"
        result["resolved_addresses"] = sorted({a[4][0] for a in addresses})[:4]
    except OSError as error:
        return {"dns": "KO", "error": type(error).__name__}
    if port is None:
        return result
    try:
        with socket.create_connection((host, port), timeout=2):
            result["tcp"] = "OK"
    except OSError as error:
        return {**result, "tcp": "KO", "error": type(error).__name__}
    if scheme not in {"http", "https"}:
        return result
    connection_type = (
        http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_type(host, port, timeout=2)
    try:
        connection.request("HEAD", "/")
        response = connection.getresponse()
        result["http_status"] = response.status
        result["http_method"] = "HEAD"
    except (OSError, http.client.HTTPException) as error:
        result["http_error"] = type(error).__name__
    finally:
        connection.close()
    return result


def diagnostic_snapshot(
    infrastructure: InfrastructureConfig,
    node_id: str,
    host_reader: Callable[[], dict],
) -> dict:
    """At most seven endpoints plus host metrics, six seconds and eight threads."""
    targets: list[tuple[str, str, int | None, str | None]] = []
    nodes = {node.id: node for node in infrastructure.nodes}
    services = sorted(infrastructure.services, key=lambda s: s.node != node_id)
    for service in services:
        node = nodes.get(service.node)
        if not service.enabled or node is None:
            continue
        raw = node.endpoint.address
        parsed = urlsplit(raw if "://" in raw else "//" + raw)
        if parsed.username or parsed.password or not parsed.hostname:
            continue
        try:
            port = service.port or parsed.port
        except ValueError:
            continue
        scheme = (
            parsed.scheme
            if parsed.scheme in {"http", "https"}
            and (service.port is None or service.port == parsed.port)
            else None
        )
        if port is None and scheme:
            port = 443 if scheme == "https" else 80
        if scheme is None and port in {80, 443, 8123}:
            scheme = "https" if port == 443 else "http"
        target = (service.id, parsed.hostname, port, scheme)
        if not any(t[1:] == target[1:] for t in targets):
            targets.append(target)
        if len(targets) == 7:
            break
    results: Queue = Queue()

    def run(target):
        try:
            result = probe_endpoint(*target[1:])
            results.put((target[0], result))
        except Exception as error:
            results.put((target[0], {"error": type(error).__name__}))
        finally:
            _SLOTS.release()

    pending = {"__host__": {}}

    def read_host():
        try:
            snapshot = host_reader()
            results.put(
                (
                    "__host__",
                    {
                        k: snapshot.get(k)
                        for k in (
                            "cpu_percent",
                            "memory_percent",
                            "disk_percent",
                            "failed_systemd_units",
                            "inactive_systemd_units",
                            "agent_restarts",
                        )
                    },
                )
            )
        except Exception as error:
            results.put(("__host__", {"error": type(error).__name__}))
        finally:
            _SLOTS.release()

    if _SLOTS.acquire(blocking=False):
        Thread(target=read_host, daemon=True).start()
    else:
        pending["__host__"]["status"] = "busy"
    for target in targets:
        pending[target[0]] = {"target": target[0], "host": target[1], "port": target[2]}
        if _SLOTS.acquire(blocking=False):
            Thread(target=run, args=(target,), daemon=True).start()
        else:
            pending[target[0]]["status"] = "busy"
    deadline = monotonic() + 6
    completed = set()
    while len(completed) < len(pending) and monotonic() < deadline:
        try:
            key, result = results.get(timeout=max(0.01, deadline - monotonic()))
        except Empty:
            break
        pending[key].update(result)
        completed.add(key)
    for key, result in pending.items():
        if key not in completed:
            result.setdefault("status", "TIMEOUT")
    host_metrics = pending.pop("__host__")
    return {
        "origin": socket.gethostname(),
        "requested_node": node_id,
        "observed_at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
        "endpoints": list(pending.values()),
        "host_metrics": host_metrics,
        "limits": "Tests depuis Agent, pas depuis le nœud distant. HTTP HEAD / sans "
        "authentification ; 401/403 ne prouvent pas une panne. Aucun fichier modifié.",
    }
