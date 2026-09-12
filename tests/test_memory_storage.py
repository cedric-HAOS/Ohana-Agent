import json

from ohana_agent.persistence.memory_entry import MemoryEntry
from ohana_agent.persistence.memory_scope import MemoryScope
from ohana_agent.persistence.memory_serializer import MemorySerializer
from ohana_agent.persistence.memory_storage import MemoryStorage


def test_storage_file_does_not_exist_initially(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "memory.json")

    assert not storage.exists()


def test_save_creates_storage_file(tmp_path) -> None:
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

    assert storage.exists()


def test_save_writes_json_payload(tmp_path) -> None:
    path = tmp_path / "memory.json"
    storage = MemoryStorage(path)

    storage.save(
        [
            MemoryEntry(
                key="device.name",
                value="pool",
                scope=MemoryScope.PERSISTENT,
            ),
        ],
    )

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload == {
        "entries": {
            "device.name": {
                "key": "device.name",
                "value": "pool",
                "scope": "PERSISTENT",
            },
        },
    }


def test_save_ignores_runtime_entries(tmp_path) -> None:
    path = tmp_path / "memory.json"
    storage = MemoryStorage(path)

    storage.save(
        [
            MemoryEntry(
                key="runtime",
                value=1,
                scope=MemoryScope.RUNTIME,
            ),
            MemoryEntry(
                key="persistent",
                value=2,
                scope=MemoryScope.PERSISTENT,
            ),
        ],
    )

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert list(payload["entries"]) == ["persistent"]


def test_save_ignores_session_entries(tmp_path) -> None:
    path = tmp_path / "memory.json"
    storage = MemoryStorage(path)

    storage.save(
        [
            MemoryEntry(
                key="session",
                value=1,
                scope=MemoryScope.SESSION,
            ),
            MemoryEntry(
                key="persistent",
                value=2,
                scope=MemoryScope.PERSISTENT,
            ),
        ],
    )

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert list(payload["entries"]) == ["persistent"]


def test_load_missing_file_returns_empty_list(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "memory.json")

    assert storage.load() == []


def test_load_saved_entries(tmp_path) -> None:
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

    entries = storage.load()

    assert len(entries) == 1
    assert entries[0].key == "device.name"
    assert entries[0].value == "pool"
    assert entries[0].scope is MemoryScope.PERSISTENT


def test_clear_deletes_storage_file(tmp_path) -> None:
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

    storage.clear()

    assert not storage.exists()


def test_clear_missing_file_does_not_fail(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "memory.json")

    storage.clear()

    assert not storage.exists()


def test_save_creates_parent_directory(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "nested" / "memory.json")

    storage.save(
        [
            MemoryEntry(
                key="device.name",
                value="pool",
                scope=MemoryScope.PERSISTENT,
            ),
        ],
    )

    assert storage.exists()


def test_save_multiple_persistent_entries(tmp_path) -> None:
    storage = MemoryStorage(tmp_path / "memory.json")

    storage.save(
        [
            MemoryEntry("a", 1, MemoryScope.PERSISTENT),
            MemoryEntry("b", 2, MemoryScope.PERSISTENT),
        ],
    )

    entries = storage.load()

    assert [(entry.key, entry.value) for entry in entries] == [
        ("a", 1),
        ("b", 2),
    ]


def test_storage_uses_injected_serializer(tmp_path) -> None:
    serializer = MemorySerializer()
    storage = MemoryStorage(
        tmp_path / "memory.json",
        serializer=serializer,
    )

    storage.save(
        [
            MemoryEntry(
                key="device.name",
                value="pool",
                scope=MemoryScope.PERSISTENT,
            ),
        ],
    )

    assert storage.load()[0].value == "pool"
