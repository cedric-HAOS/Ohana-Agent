from ohana_agent.core import Statistics


def test_statistics_can_be_instantiated() -> None:
    statistics = Statistics()

    assert isinstance(statistics, Statistics)
