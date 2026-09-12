from ohana_agent.persistence.memory_scope import MemoryScope
from ohana_agent.persistence.persistent_memory import PersistentMemory


def test_persistent_memory_stores_persistent_scope() -> None:
    memory = PersistentMemory()

    memory.set("device.name", "pool")

    entry = next(iter(memory))

    assert entry.scope is MemoryScope.PERSISTENT


def test_persistent_memory_get_value() -> None:
    memory = PersistentMemory()

    memory.set("device.name", "pool")

    assert memory.get("device.name") == "pool"
