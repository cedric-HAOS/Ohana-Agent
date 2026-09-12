from ohana_agent.persistence.memory_scope import MemoryScope


def test_runtime_scope_exists() -> None:
    assert MemoryScope.RUNTIME.name == "RUNTIME"


def test_runtime_scope_is_enum() -> None:
    assert isinstance(MemoryScope.RUNTIME, MemoryScope)


def test_session_scope_exists() -> None:
    assert MemoryScope.SESSION.name == "SESSION"


def test_session_scope_is_enum() -> None:
    assert isinstance(MemoryScope.SESSION, MemoryScope)


def test_persistent_scope_exists() -> None:
    assert MemoryScope.PERSISTENT.name == "PERSISTENT"


def test_persistent_scope_is_enum() -> None:
    assert isinstance(MemoryScope.PERSISTENT, MemoryScope)
