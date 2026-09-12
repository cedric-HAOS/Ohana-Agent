from ohana_agent.persistence.memory_entry import MemoryEntry
from ohana_agent.persistence.memory_scope import MemoryScope


def test_create_memory_entry() -> None:
    entry = MemoryEntry(
        key="temperature",
        value=23,
    )

    assert entry.key == "temperature"
    assert entry.value == 23
    assert entry.scope is MemoryScope.RUNTIME


def test_create_memory_entry_with_scope() -> None:
    entry = MemoryEntry(
        key="counter",
        value=42,
        scope=MemoryScope.RUNTIME,
    )

    assert entry.scope is MemoryScope.RUNTIME


def test_memory_entry_slots() -> None:
    entry = MemoryEntry("a", 1)

    assert not hasattr(entry, "__dict__")
