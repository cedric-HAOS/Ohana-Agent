from dataclasses import dataclass

from ohana_agent.core import Registry


@dataclass
class Item:
    id: str


class InMemoryRegistry:
    def __init__(self) -> None:
        self.items: dict[str, Item] = {}

    def add(self, item: Item) -> None:
        self.items[item.id] = item

    def remove(self, item_id: str) -> Item:
        return self.items.pop(item_id)

    def get(self, item_id: str) -> Item:
        return self.items[item_id]

    def exists(self, item_id: str) -> bool:
        return item_id in self.items

    def clear(self) -> None:
        self.items.clear()


def test_registry_protocol_accepts_matching_class() -> None:
    registry: Registry[Item] = InMemoryRegistry()
    item = Item(id="item-1")

    registry.add(item)

    assert registry.exists("item-1") is True
    assert registry.get("item-1") == item
    assert registry.remove("item-1") == item
    assert registry.exists("item-1") is False
