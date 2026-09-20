"""
Business Service — the write path ("Business Service" role in the chapter).
Owns the shared spatial indexes (geohash map + quadtree) and keeps them
consistent with the database on create/update/delete.
"""
from __future__ import annotations

from . import geohash as gh
from .cache import CacheLayer
from .config import ProximityConfig
from .database import Database
from .models import BusinessCreate, BusinessUpdate
from .quadtree import QuadPoint, Quadtree


class SpatialIndex:
    """Shared in-memory geospatial index used by both read and write paths.

    - geohash_index: {geohash_prefix -> set(business_id)}
    - quadtree: spatial tree for k-NN / radius queries
    Rebuilt from the DB at startup, maintained incrementally on writes.
    """

    def __init__(self, config: ProximityConfig):
        self._config = config
        self.geohash_index: dict[str, set[int]] = {}
        self.quadtree = Quadtree(capacity=config.quadtree_capacity,
                                 max_depth=config.quadtree_max_depth)
        self._coords: dict[int, tuple[float, float]] = {}  # id -> (lat,lng) for removal

    def add(self, business_id: int, lat: float, lng: float) -> None:
        cell = gh.encode(lat, lng, self._config.default_precision)
        self.geohash_index.setdefault(cell, set()).add(business_id)
        self.quadtree.insert(QuadPoint(lat, lng, business_id))
        self._coords[business_id] = (lat, lng)

    def cell_of(self, business_id: int) -> str | None:
        coords = self._coords.get(business_id)
        if not coords:
            return None
        return gh.encode(coords[0], coords[1], self._config.default_precision)

    @property
    def grid_count(self) -> int:
        return len(self.geohash_index)


class NotFoundError(Exception):
    pass


class BusinessService:
    def __init__(self, config: ProximityConfig, db: Database,
                 index: SpatialIndex, cache: CacheLayer):
        self._config = config
        self._db = db
        self._index = index
        self._cache = cache

    async def rebuild_indexes(self) -> None:
        """Populate geohash map + quadtree from the DB (called at startup)."""
        rows = await self._db.all()
        for r in rows:
            self._index.add(r["id"], r["lat"], r["lng"])
            self._cache.set_business(r["id"], r)

    async def create(self, req: BusinessCreate) -> int:
        bid = await self._db.insert(req.name, req.category, req.lat, req.lng, req.address)
        self._index.add(bid, req.lat, req.lng)
        # Invalidate caches
        self._cache.invalidate_business(bid)
        cell = self._index.cell_of(bid)
        if cell:
            self._cache.invalidate_geohash(cell)
        return bid

    async def update(self, business_id: int, req: BusinessUpdate) -> dict:
        existing = await self._db.get(business_id)
        if not existing:
            raise NotFoundError(f"Business {business_id} not found")

        fields = req.model_dump(exclude_none=True)
        if not fields:
            return existing
        ok = await self._db.update(business_id, fields)
        if not ok:
            raise NotFoundError(f"Business {business_id} not found")

        # If coordinates changed, rebuild index entry for this business.
        new_lat = fields.get("lat", existing["lat"])
        new_lng = fields.get("lng", existing["lng"])
        if (new_lat, new_lng) != (existing["lat"], existing["lng"]):
            self._move_in_index(business_id, existing["lat"], existing["lng"], new_lat, new_lng)

        updated = await self._db.get(business_id)
        self._cache.invalidate_business(business_id)
        if updated:
            self._cache.set_business(business_id, updated)
        return updated

    def _move_in_index(self, business_id: int, old_lat, old_lng, new_lat, new_lng) -> None:
        # Remove from old geohash cell
        old_cell = gh.encode(old_lat, old_lng, self._config.default_precision)
        ids = self._index.geohash_index.get(old_cell)
        if ids:
            ids.discard(business_id)
            if not ids:
                del self._index.geohash_index[old_cell]
        self._cache.invalidate_geohash(old_cell)
        # Add to new cell + quadtree (quadtree has no delete; mark coords for knn-filter,
        # acceptable per chapter's batch-rebuild note)
        self._index.add(business_id, new_lat, new_lng)
        self._cache.invalidate_geohash(self._index.cell_of(business_id))

    async def delete(self, business_id: int) -> None:
        existing = await self._db.get(business_id)
        if not existing:
            raise NotFoundError(f"Business {business_id} not found")
        await self._db.delete(business_id)
        # Remove from geohash index
        cell = gh.encode(existing["lat"], existing["lng"], self._config.default_precision)
        ids = self._index.geohash_index.get(cell)
        if ids:
            ids.discard(business_id)
            if not ids:
                del self._index.geohash_index[cell]
        self._index._coords.pop(business_id, None)
        self._cache.invalidate_geohash(cell)
        self._cache.invalidate_business(business_id)

    async def get(self, business_id: int) -> dict:
        cached = self._cache.get_business(business_id)
        if cached:
            return cached
        row = await self._db.get(business_id)
        if not row:
            raise NotFoundError(f"Business {business_id} not found")
        self._cache.set_business(business_id, row)
        return row
