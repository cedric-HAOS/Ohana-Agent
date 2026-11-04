"""Memory diagnostics: a census on demand and an explicit allocation trace."""

import tracemalloc

import pytest

from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.runtime.memory_diagnostics import (
    AllocationTrace,
    memory_report,
    object_census,
)


@pytest.fixture(autouse=True)
def _no_trace_left():
    yield
    if tracemalloc.is_tracing():
        tracemalloc.stop()


def test_census_counts_live_objects_by_type_largest_first():
    keep = [{"leak": index} for index in range(5000)]

    census = object_census(limit=5)

    counts = [item["count"] for item in census["types"]]
    assert counts == sorted(counts, reverse=True)
    assert len(census["types"]) == 5
    assert census["total_objects"] > 5000
    assert {item["type"] for item in census["types"]} & {
        "builtins.dict",
        "builtins.tuple",
    }
    del keep


def test_trace_names_the_site_that_grows_and_stops_cleanly():
    trace = AllocationTrace()
    assert trace.report()["tracing"] is False

    assert trace.start()["tracing"] is True
    retained = [bytes(1024) for _ in range(500)]  # ~500 KB kept alive
    report = trace.report(limit=5)

    assert report["tracing"] is True
    assert report["growth"], "the retained allocation must show up"
    assert "test_memory_diagnostics.py" in report["growth"][0]["site"]
    assert report["growth"][0]["size_diff_bytes"] >= 400_000
    assert trace.stop()["tracing"] is False
    assert not tracemalloc.is_tracing()
    del retained


def test_a_trace_started_elsewhere_is_left_running():
    tracemalloc.start()
    trace = AllocationTrace()

    trace.start()
    trace.stop()

    assert tracemalloc.is_tracing()


def test_memory_report_has_the_census_and_the_trace_state():
    report = memory_report(AllocationTrace(), limit=3)

    assert report["schema_version"] == 1
    assert len(report["census"]["types"]) == 3
    assert report["trace"] == {"tracing": False, "frames": 12}


def test_service_serves_and_controls_the_diagnostics(tmp_path):
    from ohana_agent.api.service import AdministrationService

    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infrastructure.yaml"
        )
    )

    operations = service.capabilities().operations
    assert {"agent.diagnostics.memory.read", "agent.diagnostics.memory.trace"} <= set(
        operations
    )
    assert service.control_memory_trace({"action": "start"})["tracing"] is True
    assert service.read_memory_diagnostics()["trace"]["tracing"] is True
    assert service.control_memory_trace({"action": "stop"})["tracing"] is False
    with pytest.raises(ValueError):
        service.control_memory_trace({"action": "restart"})


def test_release_collects_cycles_and_survives_a_missing_malloc_trim(monkeypatch):
    import gc

    from ohana_agent.runtime import memory_release

    class Cycle:
        pass

    first, second = Cycle(), Cycle()
    first.other, second.other = second, first
    del first, second
    gc.disable()
    try:
        calls = []
        monkeypatch.setattr(
            memory_release.ctypes,
            "CDLL",
            lambda name: calls.append(name) or (_ for _ in ()).throw(OSError(name)),
        )

        memory_release.release_freed_memory()
    finally:
        gc.enable()

    assert calls == ["libc.so.6"]


def test_every_websocket_probe_releases_memory_afterwards(monkeypatch):
    from ohana_agent.plugins.zwave import client as zwave_client

    released = []
    monkeypatch.setattr(
        zwave_client, "release_freed_memory", lambda: released.append(1)
    )

    async def probe(url, timeout, verify_tls):
        return zwave_client.ZWaveHealthResult(url=url, healthy=True)

    zwave_client.ZWaveHealthClient(websocket_query=probe).query("ws://zwave.test:3000")

    async def failing(url, timeout, verify_tls):
        raise OSError("refused")

    zwave_client.ZWaveHealthClient(websocket_query=failing).query(
        "ws://zwave.test:3000"
    )

    assert released == [1, 1]
