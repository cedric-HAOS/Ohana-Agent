from abc import ABC

from ohana_agent.observation import ObservationExporter


def test_observation_exporter_is_abstract_contract() -> None:
    assert issubclass(ObservationExporter, ABC)
    assert ObservationExporter.__abstractmethods__ == {"export"}
