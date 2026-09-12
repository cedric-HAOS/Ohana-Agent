from ohana_agent.persistence.runtime_memory import RuntimeMemory


def test_memory_is_empty() -> None:
    memory = RuntimeMemory()

    assert len(memory) == 0


def test_set_value() -> None:
    memory = RuntimeMemory()

    memory.set("temperature", 25)

    assert memory.get("temperature") == 25


def test_get_unknown_key_returns_none() -> None:
    memory = RuntimeMemory()

    assert memory.get("unknown") is None


def test_exists_true() -> None:
    memory = RuntimeMemory()

    memory.set("a", 1)

    assert memory.exists("a")


def test_exists_false() -> None:
    memory = RuntimeMemory()

    assert not memory.exists("a")


def test_delete_existing_key() -> None:
    memory = RuntimeMemory()

    memory.set("a", 1)
    memory.delete("a")

    assert memory.get("a") is None


def test_delete_unknown_key() -> None:
    memory = RuntimeMemory()

    memory.delete("unknown")

    assert len(memory) == 0


def test_clear_memory() -> None:
    memory = RuntimeMemory()

    memory.set("a", 1)
    memory.set("b", 2)

    memory.clear()

    assert len(memory) == 0


def test_keys() -> None:
    memory = RuntimeMemory()

    memory.set("a", 1)
    memory.set("b", 2)

    assert memory.keys() == ["a", "b"]


def test_values() -> None:
    memory = RuntimeMemory()

    memory.set("a", 1)
    memory.set("b", 2)

    assert memory.values() == [1, 2]


def test_items() -> None:
    memory = RuntimeMemory()

    memory.set("a", 1)
    memory.set("b", 2)

    assert memory.items() == [
        ("a", 1),
        ("b", 2),
    ]


def test_len() -> None:
    memory = RuntimeMemory()

    memory.set("a", 1)
    memory.set("b", 2)

    assert len(memory) == 2


def test_contains() -> None:
    memory = RuntimeMemory()

    memory.set("temperature", 20)

    assert "temperature" in memory


def test_contains_missing_key() -> None:
    memory = RuntimeMemory()

    assert "missing" not in memory


def test_iter_returns_entries() -> None:
    memory = RuntimeMemory()

    memory.set("a", 1)
    memory.set("b", 2)

    keys = [entry.key for entry in memory]

    assert keys == ["a", "b"]


def test_overwrite_value() -> None:
    memory = RuntimeMemory()

    memory.set("counter", 1)
    memory.set("counter", 2)

    assert memory.get("counter") == 2


def test_multiple_insertions() -> None:
    memory = RuntimeMemory()

    for i in range(100):
        memory.set(f"k{i}", i)

    assert len(memory) == 100


def test_insertion_order_is_preserved() -> None:
    memory = RuntimeMemory()

    memory.set("first", 1)
    memory.set("second", 2)
    memory.set("third", 3)

    assert memory.keys() == [
        "first",
        "second",
        "third",
    ]
