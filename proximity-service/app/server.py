"""FastAPI server — thin routing layer over LBS + Business services."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from .business_service import BusinessService, NotFoundError, SpatialIndex
from .cache import CacheLayer
from .config import ProximityConfig
from .database import Database
from .lbs_service import LBSService
from .models import (
    Business, BusinessCreate, BusinessUpdate,
    AlgorithmResult, CompareResponse, KnnResponse, NearbyResponse, StatsResponse,
)

_config: ProximityConfig | None = None
_db: Database | None = None
_cache: CacheLayer | None = None
_index: SpatialIndex | None = None
_business: BusinessService | None = None
_lbs: LBSService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _db, _cache, _index, _business, _lbs
    _config = ProximityConfig()
    _db = Database(_config)
    await _db.initialize()
    _cache = CacheLayer(_config.cache_max_size)
    _index = SpatialIndex(_config)
    _business = BusinessService(_config, _db, _index, _cache)
    _lbs = LBSService(_config, _db, _index, _cache)
    await _business.rebuild_indexes()  # load existing businesses into indexes
    yield
    await _db.close()


app = FastAPI(title="Proximity Service", lifespan=lifespan)


# ─── Business CRUD ────────────────────────────────────────────────────

@app.post("/v1/businesses", status_code=201)
async def create_business(req: BusinessCreate):
    bid = await _business.create(req)
    return {"id": bid}


@app.get("/v1/businesses/{business_id}", response_model=Business)
async def get_business(business_id: int):
    try:
        return await _business.get(business_id)
    except NotFoundError:
        raise HTTPException(404, "Business not found")


@app.put("/v1/businesses/{business_id}", response_model=Business)
async def update_business(business_id: int, req: BusinessUpdate):
    try:
        return await _business.update(business_id, req)
    except NotFoundError:
        raise HTTPException(404, "Business not found")


@app.delete("/v1/businesses/{business_id}")
async def delete_business(business_id: int):
    try:
        await _business.delete(business_id)
        return {"status": "deleted"}
    except NotFoundError:
        raise HTTPException(404, "Business not found")


# ─── Search ───────────────────────────────────────────────────────────

@app.get("/v1/search/nearby", response_model=NearbyResponse)
async def search_nearby(lat: float, lng: float,
                        radius: float = Query(default=None)):
    if lat is None or lng is None:
        raise HTTPException(400, "lat and lng required")
    r = radius if radius is not None else _config.default_radius_m
    r = max(1.0, min(r, _config.max_radius_m))
    items = await _lbs.search_nearby(lat, lng, r)
    return NearbyResponse(lat=lat, lng=lng, radius_m=r, items=items)


@app.get("/v1/search/knn", response_model=KnnResponse)
async def search_knn(lat: float, lng: float, k: int = Query(default=10, ge=1, le=100)):
    items = await _lbs.search_knn(lat, lng, k)
    return KnnResponse(lat=lat, lng=lng, k=k, items=items)


@app.get("/v1/compare", response_model=CompareResponse)
async def compare(lat: float, lng: float,
                  radius: float = Query(default=None), k: int = Query(default=10)):
    radius = radius or _config.default_radius_m

    t0 = time.perf_counter()
    geo_items = await _lbs.search_nearby(lat, lng, radius)
    geo_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    qt_items = await _lbs.search_knn(lat, lng, k)
    qt_ms = (time.perf_counter() - t0) * 1000

    return CompareResponse(
        geohash=AlgorithmResult(items=geo_items, ms=round(geo_ms, 3)),
        quadtree=AlgorithmResult(items=qt_items, ms=round(qt_ms, 3)),
    )


@app.get("/v1/stats", response_model=StatsResponse)
async def stats():
    return StatsResponse(
        businesses=await _db.count(),
        grids=_index.grid_count,
        quadtree_points=len(_index._coords),
        cache_hits=_cache.hits,
        cache_misses=_cache.misses,
    )
