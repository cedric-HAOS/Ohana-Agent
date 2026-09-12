from ohana_agent.persistence.memory_entry import MemoryEntry
from ohana_agent.persistence.memory_scope import MemoryScope
from ohana_agent.persistence.memory_serializer import MemorySerializer


def test_serialize_entry() -> None:
    serializer = MemorySerializer()
    entry = MemoryEntry(
        key="device.name",
        value="pool",
        scope=MemoryScope.PERSISTENT,
    )

    payload = serializer.serialize_entry(entry)

    assert payload == {
        "key": "device.name",
        "value": "pool",
        "scope": "PERSISTENT",
    }


def test_deserialize_entry() -> None:
    serializer = MemorySerializer()

    entry = serializer.deserialize_entry(
        {
            "key": "device.name",
            "value": "pool",
            "scope": "PERSISTENT",
        },
    )

    assert entry.key == "device.name"
    assert entry.value == "pool"
    assert entry.scope is MemoryScope.PERSISTENT


def test_serialize_entries() -> None:
    serializer = MemorySerializer()

    payload = serializer.serialize_entries(
        [
            MemoryEntry("a", 1, MemoryScope.PERSISTENT),
            MemoryEntry("b", 2, MemoryScope.PERSISTENT),
        ],
    )

    assert payload == {
        "a": {
            "key": "a",
            "value": 1,
            "scope": "PERSISTENT",
        },
        "b": {
            "key": "b",
            "value": 2,
            "scope": "PERSISTENT",
        },
    }


def test_deserialize_entries() -> None:
    serializer = MemorySerializer()

    entries = serializer.deserialize_entries(
        {
            "a": {
                "key": "a",
                "value": 1,
                "scope": "PERSISTENT",
            },
            "b": {
                "key": "b",
                "value": 2,
                "scope": "PERSISTENT",
            },
        },
    )

    assert [(entry.key, entry.value, entry.scope) for entry in entries] == [
        ("a", 1, MemoryScope.PERSISTENT),
        ("b", 2, MemoryScope.PERSISTENT),
    ]
