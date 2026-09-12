from ohana_agent.observation import (
    Observation,
    ObservationExportPipeline,
    ObservationStatus,
)
from ohana_agent.observation.exporters import InMemoryObservationExporter


def build_observation(
    *,
    node: str = "infra-01",
) -> Observation:
    return Observation(
        node=node,
        service="dns-primary",
        capability="dns",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="DNS resolution succeeded.",
        source="dns-plugin",
        latency_ms=12.5,
        metadata={
            "hostname": "example.com",
        },
    )


def test_pipeline_can_be_created_without_exporters() -> None:
    pipeline = ObservationExportPipeline()

    assert pipeline.exporters == []


def test_pipeline_can_be_created_with_exporters() -> None:
    exporter = InMemoryObservationExporter()

    pipeline = ObservationExportPipeline(
        exporters=[exporter],
    )

    assert pipeline.exporters == [exporter]


def test_pipeline_adds_exporter() -> None:
    pipeline = ObservationExportPipeline()
    exporter = InMemoryObservationExporter()

    pipeline.add_exporter(exporter)

    assert pipeline.exporters == [exporter]


def test_pipeline_removes_exporter() -> None:
    exporter = InMemoryObservationExporter()

    pipeline = ObservationExportPipeline(
        exporters=[exporter],
    )

    result = pipeline.remove_exporter(exporter)

    assert result is True
    assert pipeline.exporters == []


def test_pipeline_returns_false_when_removing_unknown_exporter() -> None:
    pipeline = ObservationExportPipeline()
    exporter = InMemoryObservationExporter()

    result = pipeline.remove_exporter(exporter)

    assert result is False


def test_pipeline_exports_observation_to_one_exporter() -> None:
    exporter = InMemoryObservationExporter()

    pipeline = ObservationExportPipeline(
        exporters=[exporter],
    )

    observation = build_observation()

    pipeline.export(observation)

    assert exporter.observations == [observation]


def test_pipeline_exports_observation_to_all_exporters() -> None:
    first_exporter = InMemoryObservationExporter()
    second_exporter = InMemoryObservationExporter()

    pipeline = ObservationExportPipeline(
        exporters=[
            first_exporter,
            second_exporter,
        ],
    )

    observation = build_observation()

    pipeline.export(observation)

    assert first_exporter.observations == [observation]
    assert second_exporter.observations == [observation]


def test_pipeline_preserves_observation_order() -> None:
    exporter = InMemoryObservationExporter()

    pipeline = ObservationExportPipeline(
        exporters=[exporter],
    )

    first = build_observation(node="infra-01")
    second = build_observation(node="zwave-01")

    pipeline.export(first)
    pipeline.export(second)

    assert exporter.observations == [
        first,
        second,
    ]


def test_pipeline_accepts_no_exporters() -> None:
    pipeline = ObservationExportPipeline()
    observation = build_observation()

    pipeline.export(observation)

    assert pipeline.exporters == []
