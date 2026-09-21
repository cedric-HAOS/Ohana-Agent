"""Tests for the finite Tsunade investigation catalogue."""

from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest

from ohana_agent.tsunade.investigations import InvestigationExecutor


class FakePlugins:
    def test(self, plugin_id: str) -> object:
        return SimpleNamespace(
            model_dump=lambda **_kwargs: {
                "plugin_id": plugin_id,
                "success": True,
                "check": f"{plugin_id}.check",
            }
        )

    def read(self, plugin_id: str) -> object:
        assert plugin_id == "backup"
        return SimpleNamespace(
            status="active",
            enabled=True,
            last_execution_at=None,
            last_error=None,
        )


def _executor() -> InvestigationExecutor:
    return InvestigationExecutor(
        plugins=FakePlugins(),  # type: ignore[arg-type]
        host_health_reader=lambda: {
            "memory_percent": 42.0,
            "memory_total_bytes": 1024,
            "memory_available_bytes": 512,
            "swap_percent": 0.0,
            "swap_total_bytes": 0,
            "swap_used_bytes": 0,
        },
    )


def test_read_only_snapshot_passes_explicit_http_configuration(monkeypatch):
    calls = []

    def snapshot(infrastructure, node, host_reader, **kwargs):
        calls.append((infrastructure, node, kwargs["configured_http_target"]))
        return {"requested_node": node}

    monkeypatch.setattr(
        "ohana_agent.tsunade.investigations.diagnostic_snapshot", snapshot
    )
    executor = InvestigationExecutor(
        plugins=FakePlugins(),
        host_health_reader=lambda: {},
        infrastructure_reader=lambda: "architecture",
        http_target_reader=lambda node: (
            f"supervisor-http:{node}",
            "http://ha.test:8123",
        ),
    )
    assert executor.read_only_snapshot("ha-01") == {"requested_node": "ha-01"}
    assert calls == [
        ("architecture", "ha-01", ("supervisor-http:ha-01", "http://ha.test:8123"))
    ]


def test_catalog_and_structured_execution_reuse_existing_plugin_checks() -> None:
    executor = _executor()
    assert "network.ping" in {item.operation for item in executor.catalog()}
    result = executor.execute(
        {
            "operation": "dns.query",
            "parameters": {},
            "timeout_seconds": 10,
        }
    )
    assert result.status == "OK"
    assert result.result["plugin_id"] == "dns"


def test_operation_and_parameters_must_be_explicitly_authorized() -> None:
    executor = _executor()
    with pytest.raises(ValueError, match="not authorized"):
        executor.execute({"operation": "shell.run"})
    with pytest.raises(ValueError, match="no arbitrary parameters"):
        executor.execute(
            {"operation": "network.ping", "parameters": {"host": "example.com"}}
        )


def test_timeout_returns_without_waiting_for_the_bounded_probe() -> None:
    executor = _executor()
    executor._operations["test.slow"] = (  # noqa: SLF001 - contract test.
        "Slow test probe",
        1,
        lambda: Event().wait(2) or {},
    )
    started = monotonic()
    result = executor.execute(
        {"operation": "test.slow", "parameters": {}, "timeout_seconds": 1}
    )
    assert result.status == "TIMEOUT"
    assert monotonic() - started < 1.5


def test_backup_status_exposes_latest_distributed_failure() -> None:
    failed_job = SimpleNamespace(
        status=SimpleNamespace(value="FAILED"),
        error=SimpleNamespace(message="Vision indisponible avant le transfert"),
        model_dump=lambda **_kwargs: {
            "type": "backup.infra",
            "status": "FAILED",
            "error": {"message": "Vision indisponible avant le transfert"},
        },
    )
    executor = InvestigationExecutor(
        plugins=FakePlugins(),  # type: ignore[arg-type]
        host_health_reader=lambda: {},
        jobs=SimpleNamespace(latest=lambda job_type: failed_job),  # type: ignore[arg-type]
    )
    result = executor.execute({"operation": "backup.status", "timeout_seconds": 5})
    assert result.result["status"] == "FAILED"
    assert result.result["last_error"] == "Vision indisponible avant le transfert"
    assert result.result["latest_distributed_job"]["type"] == "backup.infra"


def test_backup_status_redacts_distributed_failure_credentials() -> None:
    failed_job = SimpleNamespace(
        status=SimpleNamespace(value="FAILED"),
        error=SimpleNamespace(
            message=(
                "Upload failed for "
                "https://operator:fictional-password@backup.test/archive"
                "?access_token=fake-access-token "
                "Authorization: Bearer fake-bearer-token"
            )
        ),
        model_dump=lambda **_kwargs: {
            "type": "backup.infra",
            "status": "FAILED",
            "error": {
                "message": (
                    "Upload failed for "
                    "https://operator:fictional-password@backup.test/archive"
                    "?access_token=fake-access-token "
                    "Authorization: Bearer fake-bearer-token"
                )
            },
        },
    )

    executor = InvestigationExecutor(
        plugins=FakePlugins(),  # type: ignore[arg-type]
        host_health_reader=lambda: {},
        jobs=SimpleNamespace(latest=lambda job_type: failed_job),  # type: ignore[arg-type]
    )

    result = executor.execute(
        {
            "operation": "backup.status",
            "timeout_seconds": 5,
        }
    )

    rendered = result.model_dump_json()

    for secret in (
        "fictional-password",
        "fake-access-token",
        "fake-bearer-token",
    ):
        assert secret not in rendered

    assert "backup.test/archive" in rendered
    assert "[redacted]" in rendered


def test_probe_exception_does_not_export_credentials(caplog) -> None:
    executor = _executor()

    def unavailable():
        raise RuntimeError("http://operator:fictional-password@host/stok=fake-session/")

    executor.host_health_reader = unavailable
    result = executor.execute({"operation": "memory.status", "timeout_seconds": 1})
    assert result.status == "KO"
    assert result.result == {}
    assert result.error == "RuntimeError"
    for secret in ("fictional-password", "fake-session"):
        assert secret not in result.model_dump_json()
        assert secret not in caplog.text
