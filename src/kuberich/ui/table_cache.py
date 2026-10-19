"""Release native table-cache links when their render values are retired."""

from textual.cache import LRUCache


class RenderCache[Key, Value](LRUCache[Key, Value]):
    """Keep native LRU behavior and break its discarded linked-list rings.

    Textual 8.2.8 clears the ring's owner without unlinking its entries. Retired
    render values then wait for cyclic collection. Only owned table caches use
    this subclass; capacity, key order, lookup and eviction remain native.
    """

    def clear(self) -> None:
        entries = tuple(self._cache.values())
        super().clear()
        for entry in entries:
            entry.clear()

    def discard(self, key: Key) -> None:
        entry = self._cache.get(key)
        super().discard(key)
        if entry is not None:
            entry.clear()

    def __del__(self) -> None:
        self.clear()
