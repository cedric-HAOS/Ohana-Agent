from ohana_agent.persistence.memory_statistics import MemoryStatistics


def test_memory_statistics_defaults_to_zero() -> None:
    statistics = MemoryStatistics()

    assert statistics.hits == 0
    assert statistics.misses == 0
    assert statistics.sets == 0
    assert statistics.deletes == 0
    assert statistics.clears == 0
    assert statistics.saves == 0
    assert statistics.loads == 0


def test_memory_statistics_reset() -> None:
    statistics = MemoryStatistics(
        hits=1,
        misses=2,
        sets=3,
        deletes=4,
        clears=5,
        saves=6,
        loads=7,
    )

    statistics.reset()

    assert statistics.hits == 0
    assert statistics.misses == 0
    assert statistics.sets == 0
    assert statistics.deletes == 0
    assert statistics.clears == 0
    assert statistics.saves == 0
    assert statistics.loads == 0
