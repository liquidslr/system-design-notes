"""
Location-Based Service — the read path ("LBS" role in the chapter).
Read-heavy, stateless business logic over the shared spatial index + cache.

Two search strategies implemented per chapter:
  - search_nearby: Geohash-based radius search (center + 8 neighbors)
  - search_knn:    Quadtree k-nearest search
"""
from __future__ import annotations

import asyncio

from . import geohash as gh
from .business_service import SpatialIndex
from .cache import CacheLayer
from .config import ProximityConfig
from .database import Database
from .geo import haversine_m
from .models import Business, SearchResult


class LBSService:
    def __init__(self, config: ProximityConfig, db: Database,
                 index: SpatialIndex, cache: CacheLayer):
        self._config = config
        self._db = db
        self._index = index
        self._cache = cache

    # ─── Geohash radius search ────────────────────────────────────────

    async def search_nearby(self, lat: float, lng: float, radius_m: float) -> list[SearchResult]:
        precision = self._config.default_precision
        center = gh.encode(lat, lng, precision)
        cells = [center] + gh.neighbors(center)

        candidate_ids: set[int] = set()
        for cell in cells:
            ids = await self._ids_for_cell(cell)
            candidate_ids.update(ids)

        results: list[SearchResult] = []
        for bid in candidate_ids:
            biz = await self._load_business(bid)
            if not biz:
                continue
            dist = haversine_m(lat, lng, biz["lat"], biz["lng"])
            if dist <= radius_m:
                results.append(SearchResult(business=Business(**biz), distance_m=round(dist, 2)))

        results.sort(key=lambda r: r.distance_m)
        return results

    async def _ids_for_cell(self, cell: str) -> list[int]:
        """Return business ids for a cell, hitting the two-level cache first.
        Parallel Redis queries in the chapter are emulated by a single lookup."""
        cached = self._cache.get_ids(cell)
        if cached is not None:
            return cached
        ids = sorted(self._index.geohash_index.get(cell, set()))
        self._cache.set_ids(cell, ids)
        return ids

    # ─── Quadtree k-nearest ───────────────────────────────────────────

    async def search_knn(self, lat: float, lng: float, k: int) -> list[SearchResult]:
        if k <= 0:
            return []
        points = self._index.quadtree.query_knn(lat, lng, k * 2)
        results: list[SearchResult] = []
        seen: set[int] = set()
        for p in points:
            bid = p.payload
            if bid in seen:
                continue
            # Skip stale quadtree entries whose coords changed/deleted (no-tree-delete note)
            coords = self._index._coords.get(bid)
            if coords is None or (coords[0], coords[1]) != (p.lat, p.lng):
                continue
            biz = await self._load_business(bid)
            if not biz:
                continue
            seen.add(bid)
            results.append(SearchResult(
                business=Business(**biz),
                distance_m=round(haversine_m(lat, lng, biz["lat"], biz["lng"]), 2),
            ))
            if len(results) >= k:
                break
        results.sort(key=lambda r: r.distance_m)
        return results

    # ─── Shared helper ────────────────────────────────────────────────

    async def _load_business(self, bid: int) -> dict | None:
        cached = self._cache.get_business(bid)
        if cached is not None:
            return cached
        row = await self._db.get(bid)
        if row:
            self._cache.set_business(bid, row)
        return row
