"""
Two-level LRU cache mirroring the chapter's caching strategy:
  - geohash  -> [business_id, ...]   (the "better key" than raw coordinates)
  - business_id -> business details
Tracks hit/miss counters for /v1/stats.
"""
from __future__ import annotations

from collections import OrderedDict


class LRUCache:
    def __init__(self, max_size: int = 1024):
        self._max = max_size
        self._data: OrderedDict = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key):
        if key in self._data:
            self._data.move_to_end(key)
            self.hits += 1
            return self._data[key]
        self.misses += 1
        return None

    def set(self, key, value) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        if len(self._data) > self._max:
            self._data.popitem(last=False)

    def invalidate(self, key) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class CacheLayer:
    """Combines the two cache tiers used by the LBS read path."""

    def __init__(self, max_size: int = 1024):
        self.ids_by_geohash = LRUCache(max_size)
        self.details_by_id = LRUCache(max_size)

    # geohash -> [ids]
    def get_ids(self, geohash: str) -> list[int] | None:
        return self.ids_by_geohash.get(geohash)

    def set_ids(self, geohash: str, ids: list[int]) -> None:
        self.ids_by_geohash.set(geohash, ids)

    def invalidate_geohash(self, geohash: str) -> None:
        self.ids_by_geohash.invalidate(geohash)

    # id -> business dict
    def get_business(self, business_id: int) -> dict | None:
        return self.details_by_id.get(business_id)

    def set_business(self, business_id: int, data: dict) -> None:
        self.details_by_id.set(business_id, data)

    def invalidate_business(self, business_id: int) -> None:
        self.details_by_id.invalidate(business_id)

    @property
    def hits(self) -> int:
        return self.ids_by_geohash.hits + self.details_by_id.hits

    @property
    def misses(self) -> int:
        return self.ids_by_geohash.misses + self.details_by_id.misses
