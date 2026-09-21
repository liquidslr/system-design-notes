# Proximity Service (Nearby Location Search) — Implementation Spec

## Goal
Implement a runnable proximity service based on the design in `16. Proximity Service/Readme.md`. It lets users search for nearby businesses by location + radius, and lets business owners add/update/delete businesses. The chapter's two main geospatial indexing strategies — **Geohash** (grid-based, radius search) and **Quadtree** (in-memory tree, k-nearest search) — are both fully implemented and can be compared side-by-side. Google S2 is described in comments only (conceptual). Deployment-level concerns (multi-region, Redis, real sharding, GDPR tooling) are represented by module boundaries and comments, not actual infrastructure.

## Scope Decision
- **Algorithms:** Geohash (encode/decode/neighbors/precision + radius search) **and** Quadtree (insert/split/k-nearest/radius). Both implemented, cross-validated against each other. S2 = comments only.
- **Range:** core logic complete, single-machine simulation. One FastAPI process + SQLite for the businesses table + in-memory spatial indexes (geohash map + quadtree) built at startup. No Docker, no web frontend.
- **Interaction:** a `proximity-cli` client script, a scripted `--demo` storyline, and pytest unit tests. Matches sibling subprojects (google-drive, notification-system).

## Architecture

### Directory Structure
```
proximity-service/
├── app/
│   ├── __init__.py
│   ├── config.py            # ProximityConfig (precision table, default radius, port)
│   ├── models.py            # Pydantic models (Business, SearchResult, etc.)
│   ├── database.py          # aiosqlite businesses table CRUD
│   ├── geo.py               # Haversine distance + bounding box helpers
│   ├── geohash.py           # Geohash encode/decode/neighbors/precision-for-radius
│   ├── quadtree.py          # Quadtree spatial index + k-nearest + radius query
│   ├── cache.py             # Two-level LRU cache (geohash->ids, id->details)
│   ├── lbs_service.py       # Read path: geohash radius search + quadtree knn
│   ├── business_service.py  # Write path: add/update/delete + index maintenance
│   └── server.py            # FastAPI app + REST routes
├── cli.py                   # proximity-cli (add/search/knn/get/delete/compare/stats)
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_geo.py
│   ├── test_geohash.py
│   ├── test_quadtree.py
│   └── test_search.py
├── __main__.py              # python -m proximity_service {--server|--demo|--cli ...}
├── requirements.txt
└── README.md
```

### Component Responsibilities & Boundaries
- **geo.py** — pure math, no I/O. `haversine_m(lat1,lng1,lat2,lng2)`, `bounding_box(lat,lng,radius_m) -> (min_lat,max_lat,min_lng,max_lng)`. Single source of truth for distance.
- **geohash.py** — pure functions, no I/O. `encode(lat,lng,precision)->str`, `decode(gh)->(lat,lng,lat_err,lng_err)`, `neighbors(gh)->list[str]` (8 cells), `precision_for_radius(meters)->int`, and a `full_geohash_length` mapping table from the chapter. Interleaves longitude/latitude bits then base32-encodes.
- **quadtree.py** — pure in-memory structure, no I/O. `QuadPoint(lat,lng,payload)`, `QuadNode(bbox, capacity, depth, ...)` with `insert`, `query_radius(lat,lng,radius_m)`, `query_knn(lat,lng,k)`. Depth cap prevents unbounded subdivision on duplicate coordinates.
- **database.py** — SQLite `businesses` table; async via aiosqlite. Owns persistence only.
- **cache.py** — two LRU layers keyed per the chapter: `geohash -> [business_id,...]` and `business_id -> business_dict`. Tracks hit/miss counters for `/stats`.
- **lbs_service.py** — the read-heavy "Location-Based Service". Coordinates cache + indexes; implements `search_nearby` (geohash path) and `search_knn` (quadtree path). Holds the in-memory geohash map and quadtree.
- **business_service.py** — the "Business Service". CRUD on businesses + keeps geohash map, quadtree, and cache consistent on writes.
- **server.py** — thin FastAPI routers over the two services. No business logic.

Dependency direction: `server -> {lbs_service, business_service} -> {geohash, quadtree, geo, cache, database}`. `geohash`, `quadtree`, `geo` depend on nothing internal (pure, unit-testable).

## Data Model

| Table | Fields | Purpose |
|-------|--------|---------|
| `businesses` | id (PK), name, category, lat, lng, address, created_at | Business detail record |

In-memory indexes (rebuilt from DB at startup, maintained incrementally on writes):
- `geohash_index: dict[str, set[int]]` — maps a geohash prefix (fixed default precision) to business ids in that cell.
- `quadtree: QuadNode` — spatial tree of all businesses for k-NN.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/businesses` | POST | Add a business (name, category, lat, lng, address) |
| `/v1/businesses/{id}` | GET | Fetch business details |
| `/v1/businesses/{id}` | PUT | Update a business (may move coordinates) |
| `/v1/businesses/{id}` | DELETE | Remove a business |
| `/v1/search/nearby?lat&lng&radius` | GET | Geohash radius search; results sorted by distance |
| `/v1/search/knn?lat&lng&k` | GET | Quadtree k-nearest neighbors |
| `/v1/compare?lat&lng&radius&k` | GET | Run both algorithms, return results + latency for comparison |
| `/v1/stats` | GET | Business count, grid count, cache hit/miss, index sizes |

## Core Flows

### Business Write (add/update/delete)
1. `business_service.createBusiness` validates lat∈[-90,90], lng∈[-180,180]; insert into DB.
2. Compute geohash at default precision; add id to `geohash_index[gh]`; `quadtree.insert(QuadPoint(...))`; invalidate the cell's list-cache and the id's detail-cache.
3. Update/delete mirror this: remove/replace entries in both indexes and invalidate caches. (Chapter: business updates are not real-time, so incremental maintenance is acceptable.)

### Geohash Radius Search (`/search/nearby`)
1. Choose `precision = precision_for_radius(radius_m)` (chapter's radius→length table), min with index precision if a precomputed index at fixed precision is used.
2. Compute center geohash + 8 neighbors (solves the chapter's boundary issue).
3. Collect candidate business ids from `geohash_index` for those cells (cache-backed).
4. For each candidate, `haversine` to the query point; keep those within `radius_m`; sort ascending by distance.
5. Populate response from detail cache / DB.

### Quadtree k-Nearest (`/search/knn`)
1. `quadtree.query_knn(lat, lng, k)` uses a max-heap of size k plus bbox-distance pruning to visit only relevant subtrees.
2. Return the k nearest businesses sorted ascending by distance.

### Compare (`/v1/compare`)
Run both `search_nearby` and `search_knn` on the same input with timing; return `{geohash: {results, ms}, quadtree: {results, ms}}` to demonstrate the chapter's tradeoff discussion empirically.

### Cache
- `nearby` lookups first try `geohash_index`-cell result cache (`geohash -> [ids]`); detail fetch uses `id -> dict` cache. Hit/miss counters exposed via `/v1/stats`.

## Configuration (`config.py`, `ProximityConfig` dataclass)
- `default_precision: int = 6` (≈±0.61 km cell, per chapter table)
- `default_radius_m: int = 5000`
- `max_radius_m: int = 50000`
- `quadtree_capacity: int = 100` (chapter's per-node business cap before split)
- `quadtree_max_depth: int = 12`
- `cache_max_size: int = 1024`
- `db_path`, `data_dir`, `host`, `port` (9300), `seed_demo_businesses: bool`

`precision_for_radius` uses the chapter's table:
| length | ~precision |
|---|---|
| 4 | 39 km |
| 5 | 4.9 km |
| 6 | 1.2 km |
| 7 | 153 m |
| 8 | 19 m |

## Error Handling
- Out-of-range lat/lng → `400`. Unknown business id → `404`. Duplicate id → `409`. Negative/oversized radius → clamped to `[1, max_radius_m]`. `k <= 0` → `400`. Empty result → `200` with `[]`.

## Testing
- **test_geo.py**: haversine known distances (e.g., SF coordinates); bounding-box sanity.
- **test_geohash.py**: encode/decode round-trip within cell error; neighbors of a known cell (against reference values); `precision_for_radius` monotonicity; **boundary regression**: two points <150 m apart but in different cells are both found via neighbor search.
- **test_quadtree.py**: insert + split at capacity; `query_knn` matches brute-force nearest-k; `query_radius` matches brute-force.
- **test_search.py**: end-to-end via FastAPI TestClient — add businesses, `/search/nearby` sorted by distance, `/search/knn` returns k, `/compare` both agree on top-N, cache hit counter increments on repeat query, delete removes from results.
- **`--demo`**: seed a neighborhood of businesses (e.g., around San Francisco), then demonstrate a 500 m radius search, a k=5 knn query, a boundary-issue case captured by neighbors, and print `/compare` + `/stats` to show algorithm tradeoffs and cache hits.

## Out of Scope (YAGNI)
Real Redis/memcached, multi-region deployment, database read-replica replication logic, actual sharding, S2/Hilbert curve implementation, GDPR/CCPA compliance tooling, frontend UI, map-tile rendering. These are represented by module comments and the in-memory cache abstraction.

## Tech Stack
- Python 3.11, FastAPI, uvicorn, aiosqlite, Pydantic v2, stdlib `heapq`/`math`, pytest + pytest-asyncio + httpx TestClient.

## Data Flow Summary
1. Business writes → DB insert → update geohash map + quadtree + invalidate cache.
2. Radius search → precision-from-radius → center+8 neighbor cells → candidate ids → haversine filter → distance-sorted results.
3. k-NN search → quadtree pruned best-first search → k nearest.
4. `/compare` runs both and reports latency; `/stats` reports cache effectiveness.
