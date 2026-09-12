from ohana_agent.persistence.memory_entry import MemoryEntry
from ohana_agent.persistence.memory_manager import MemoryManager
from ohana_agent.persistence.memory_scope import MemoryScope
from ohana_agent.persistence.memory_storage import MemoryStorage
from ohana_agent.persistence.persistent_memory import PersistentMemory
from ohana_agent.persistence.runtime_memory import RuntimeMemory
from ohana_agent.persistence.session_memory import SessionMemory


def test_memory_manager_is_empty() -> None:
    manager = MemoryManager()

    assert len(manager) == 0


def test_set_value() -> None:
    manager = MemoryManager()

    manager.set("temperature", 25)

    assert manager.get("temperature") == 25


def test_get_unknown_key_returns_none() -> None:
    manager = MemoryManager()

    assert manager.get("unknown") is None


def test_exists_true() -> None:
    manager = MemoryManager()

    manager.set("a", 1)

    assert manager.exists("a")


def test_exists_false() -> None:
    manager = MemoryManager()

    assert not manager.exists("a")


def test_delete_existing_key() -> None:
    manager = MemoryManager()

    manager.set("a", 1)
    manager.delete("a")

    assert manager.get("a") is None


def test_delete_unknown_key() -> None:
    manager = MemoryManager()

    manager.delete("unknown")

    assert len(manager) == 0


def test_clear_memory() -> None:
    manager = MemoryManager()

    manager.set("a", 1)
    manager.set("b", 2)

    manager.clear()

    assert len(manager) == 0


def test_keys() -> None:
    manager = MemoryManager()

    manager.set("a", 1)
    manager.set("b", 2)

    assert manager.keys() == ["a", "b"]


def test_values() -> None:
    manager = MemoryManager()

    manager.set("a", 1)
    manager.set("b", 2)

    assert manager.values() == [1, 2]


def test_items() -> None:
    manager = MemoryManager()

    manager.set("a", 1)
    manager.set("b", 2)

    assert manager.items() == [
        ("a", 1),
        ("b", 2),
    ]


def test_contains() -> None:
    manager = MemoryManager()

    manager.set("temperature", 20)

    assert "temperature" in manager


def test_contains_missing_key() -> None:
    manager = MemoryManager()

    assert "missing" not in manager


def test_iter_returns_entries() -> None:
    manager = MemoryManager()

    manager.set("a", 1)
    manager.set("b", 2)

    entries = list(manager)

    assert all(isinstance(entry, MemoryEntry) for entry in entries)
    assert [entry.key for entry in entries] == ["a", "b"]


def test_manager_uses_injected_runtime_memory() -> None:
    runtime_memory = RuntimeMemory()
    runtime_memory.set("existing", 42)

    manager = MemoryManager(runtime_memory=runtime_memory)

    assert manager.get("existing") == 42


def test_manager_preserves_runtime_scope() -> None:
    manager = MemoryManager()

    manager.set("a", 1)

    entry = next(iter(manager))

    assert entry.scope is MemoryScope.RUNTIME


def test_manager_set_session_value() -> None:
    manager = MemoryManager()

    manager.set("user", "cedric", scope=MemoryScope.SESSION)

    assert manager.get("user", scope=MemoryScope.SESSION) == "cedric"


def test_runtime_and_session_are_isolated() -> None:
    manager = MemoryManager()

    manager.set("same", "runtime")
    manager.set("same", "session", scope=MemoryScope.SESSION)

    assert manager.get("same") == "runtime"
    assert manager.get("same", scope=MemoryScope.SESSION) == "session"


def test_delete_session_value() -> None:
    manager = MemoryManager()

    manager.set("user", "cedric", scope=MemoryScope.SESSION)
    manager.delete("user", scope=MemoryScope.SESSION)

    assert manager.get("user", scope=MemoryScope.SESSION) is None


def test_clear_session_memory() -> None:
    manager = MemoryManager()

    manager.set("runtime", 1)
    manager.set("session", 2, scope=MemoryScope.SESSION)

    manager.clear(scope=MemoryScope.SESSION)

    assert manager.get("runtime") == 1
    assert manager.get("session", scope=MemoryScope.SESSION) is None


def test_session_keys() -> None:
    manager = MemoryManager()

    manager.set("a", 1, scope=MemoryScope.SESSION)
    manager.set("b", 2, scope=MemoryScope.SESSION)

    assert manager.keys(scope=MemoryScope.SESSION) == ["a", "b"]


def test_manager_uses_injected_session_memory() -> None:
    session_memory = SessionMemory()
    session_memory.set("session", 42)

    manager = MemoryManager(session_memory=session_memory)

    assert manager.get("session", scope=MemoryScope.SESSION) == 42


def test_manager_preserves_session_scope() -> None:
    manager = MemoryManager()

    manager.set("a", 1, scope=MemoryScope.SESSION)

    session_entries = [
        entry
        for entry in manager._session_memory  # noqa: SLF001
    ]

    assert session_entries[0].scope is MemoryScope.SESSION


def test_manager_set_persistent_value() -> None:
    manager = MemoryManager()

    manager.set("device.name", "pool", scope=MemoryScope.PERSISTENT)

    assert manager.get("device.name", scope=MemoryScope.PERSISTENT) == "pool"


def test_runtime_session_and_persistent_are_isolated() -> None:
    manager = MemoryManager()

    manager.set("same", "runtime")
    manager.set("same", "session", scope=MemoryScope.SESSION)
    manager.set("same", "persistent", scope=MemoryScope.PERSISTENT)

    assert manager.get("same") == "runtime"
    assert manager.get("same", scope=MemoryScope.SESSION) == "session"
    assert manager.get("same", scope=MemoryScope.PERSISTENT) == "persistent"


def test_delete_persistent_value() -> None:
    manager = MemoryManager()

    manager.set("device.name", "pool", scope=MemoryScope.PERSISTENT)
    manager.delete("device.name", scope=MemoryScope.PERSISTENT)

    assert manager.get("device.name", scope=MemoryScope.PERSISTENT) is None


def test_clear_persistent_memory() -> None:
    manager = MemoryManager()

    manager.set("runtime", 1)
    manager.set("session", 2, scope=MemoryScope.SESSION)
    manager.set("persistent", 3, scope=MemoryScope.PERSISTENT)

    manager.clear(scope=MemoryScope.PERSISTENT)

    assert manager.get("runtime") == 1
    assert manager.get("session", scope=MemoryScope.SESSION) == 2
    assert manager.get("persistent", scope=MemoryScope.PERSISTENT) is None


def test_persistent_keys() -> None:
    manager = MemoryManager()

    manager.set("a", 1, scope=MemoryScope.PERSISTENT)
    manager.set("b", 2, scope=MemoryScope.PERSISTENT)

    assert manager.keys(scope=MemoryScope.PERSISTENT) == ["a", "b"]


def test_manager_uses_injected_persistent_memory() -> None:
    persistent_memory = PersistentMemory()
    persistent_memory.set("device.name", "pool")

    manager = MemoryManager(persistent_memory=persistent_memory)

    assert manager.get("device.name", scope=MemoryScope.PERSISTENT) == "pool"


def test_manager_preserves_persistent_scope() -> None:
    manager = MemoryManager()

    manager.set("a", 1, scope=MemoryScope.PERSISTENT)

    persistent_entries = [
        entry
        for entry in manager._persistent_memory  # noqa: SLF001
    ]

    assert persistent_entries[0].scope is MemoryScope.PERSISTENT


def test_save_persistent_without_storage_does_not_fail() -> None:
    manager = MemoryManager()

    manager.save_persistent()


def test_load_persistent_without_storage_does_not_fail() -> None:
    manager = MemoryManager()

    manager.load_persistent()


def test_save_persistent_writes_persistent_memory(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "memory.json")
    manager = MemoryManager(storage=storage)

    manager.set("device.name", "pool", scope=MemoryScope.PERSISTENT)

    manager.save_persistent()

    entries = storage.load()

    assert len(entries) == 1
    assert entries[0].key == "device.name"
    assert entries[0].value == "pool"
    assert entries[0].scope is MemoryScope.PERSISTENT


def test_save_persistent_ignores_runtime_and_session(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "memory.json")
    manager = MemoryManager(storage=storage)

    manager.set("runtime", 1)
    manager.set("session", 2, scope=MemoryScope.SESSION)
    manager.set("persistent", 3, scope=MemoryScope.PERSISTENT)

    manager.save_persistent()

    entries = storage.load()

    assert [(entry.key, entry.value) for entry in entries] == [
        ("persistent", 3),
    ]


def test_load_persistent_restores_persistent_memory(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "memory.json")
    storage.save(
        [
            MemoryEntry(
                key="device.name",
                value="pool",
                scope=MemoryScope.PERSISTENT,
            ),
        ],
    )

    manager = MemoryManager(storage=storage)

    manager.load_persistent()

    assert manager.get("device.name", scope=MemoryScope.PERSISTENT) == "pool"


def test_load_persistent_clears_previous_persistent_memory(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "memory.json")
    storage.save(
        [
            MemoryEntry(
                key="from.storage",
                value=True,
                scope=MemoryScope.PERSISTENT,
            ),
        ],
    )

    manager = MemoryManager(storage=storage)
    manager.set("old", "value", scope=MemoryScope.PERSISTENT)

    manager.load_persistent()

    assert manager.get("old", scope=MemoryScope.PERSISTENT) is None
    assert manager.get("from.storage", scope=MemoryScope.PERSISTENT) is True


def test_load_persistent_does_not_touch_runtime_or_session(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "memory.json")
    storage.save(
        [
            MemoryEntry(
                key="persistent",
                value=3,
                scope=MemoryScope.PERSISTENT,
            ),
        ],
    )

    manager = MemoryManager(storage=storage)
    manager.set("runtime", 1)
    manager.set("session", 2, scope=MemoryScope.SESSION)

    manager.load_persistent()

    assert manager.get("runtime") == 1
    assert manager.get("session", scope=MemoryScope.SESSION) == 2
    assert manager.get("persistent", scope=MemoryScope.PERSISTENT) == 3


def test_manager_routes_all_supported_scopes() -> None:
    manager = MemoryManager()

    manager.set("runtime", 1, scope=MemoryScope.RUNTIME)
    manager.set("session", 2, scope=MemoryScope.SESSION)
    manager.set("persistent", 3, scope=MemoryScope.PERSISTENT)

    assert manager.get("runtime", scope=MemoryScope.RUNTIME) == 1
    assert manager.get("session", scope=MemoryScope.SESSION) == 2
    assert manager.get("persistent", scope=MemoryScope.PERSISTENT) == 3


def test_manager_exposes_statistics() -> None:
    manager = MemoryManager()

    assert manager.statistics.sets == 0


def test_manager_statistics_count_sets() -> None:
    manager = MemoryManager()

    manager.set("a", 1)
    manager.set("b", 2)

    assert manager.statistics.sets == 2


def test_manager_statistics_count_hits() -> None:
    manager = MemoryManager()

    manager.set("a", 1)
    manager.get("a")

    assert manager.statistics.hits == 1


def test_manager_statistics_count_misses() -> None:
    manager = MemoryManager()

    manager.get("missing")

    assert manager.statistics.misses == 1


def test_manager_statistics_count_deletes() -> None:
    manager = MemoryManager()

    manager.delete("missing")

    assert manager.statistics.deletes == 1


def test_manager_statistics_count_clears() -> None:
    manager = MemoryManager()

    manager.clear()

    assert manager.statistics.clears == 1


def test_manager_statistics_count_saves(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "memory.json")
    manager = MemoryManager(storage=storage)

    manager.save_persistent()

    assert manager.statistics.saves == 1


def test_manager_statistics_does_not_count_save_without_storage() -> None:
    manager = MemoryManager()

    manager.save_persistent()

    assert manager.statistics.saves == 0


def test_manager_statistics_count_loads(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "memory.json")
    manager = MemoryManager(storage=storage)

    manager.load_persistent()

    assert manager.statistics.loads == 1


def test_manager_statistics_does_not_count_load_without_storage() -> None:
    manager = MemoryManager()

    manager.load_persistent()

    assert manager.statistics.loads == 0
