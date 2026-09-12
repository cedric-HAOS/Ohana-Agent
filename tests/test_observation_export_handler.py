from ohana_agent.observation import (
    Observation,
    ObservationExportHandler,
    ObservationExportPipeline,
    ObservationPublished,
    ObservationStatus,
)
from ohana_agent.observation.exporters import InMemoryObservationExporter


def build_observation() -> Observation:
    return Observation(
        node="infra-01",
        service="dns-primary",
        capability="dns",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="DNS resolution succeeded.",
        source="dns-plugin",
    )


def test_export_handler_can_be_created() -> None:
    pipeline = ObservationExportPipeline()

    handler = ObservationExportHandler(
        pipeline=pipeline,
    )

    assert handler.pipeline is pipeline


def test_export_handler_exports_event_observation() -> None:
    exporter = InMemoryObservationExporter()
    pipeline = ObservationExportPipeline(
        exporters=[exporter],
    )
    handler = ObservationExportHandler(
        pipeline=pipeline,
    )

    observation = build_observation()
    event = ObservationPublished(
        observation=observation,
    )

    handler.handle(event)

    assert exporter.observations == [observation]


def test_export_handler_exports_to_all_pipeline_exporters() -> None:
    first_exporter = InMemoryObservationExporter()
    second_exporter = InMemoryObservationExporter()

    pipeline = ObservationExportPipeline(
        exporters=[
            first_exporter,
            second_exporter,
        ],
    )
    handler = ObservationExportHandler(
        pipeline=pipeline,
    )

    observation = build_observation()

    handler.handle(
        ObservationPublished(
            observation=observation,
        )
    )

    assert first_exporter.observations == [observation]
    assert second_exporter.observations == [observation]
