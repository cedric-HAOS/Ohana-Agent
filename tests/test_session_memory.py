from ohana_agent.persistence.memory_scope import MemoryScope
from ohana_agent.persistence.session_memory import SessionMemory


def test_session_memory_stores_session_scope() -> None:
    memory = SessionMemory()

    memory.set("user", "cedric")

    entry = next(iter(memory))

    assert entry.scope is MemoryScope.SESSION


def test_session_memory_get_value() -> None:
    memory = SessionMemory()

    memory.set("user", "cedric")

    assert memory.get("user") == "cedric"
