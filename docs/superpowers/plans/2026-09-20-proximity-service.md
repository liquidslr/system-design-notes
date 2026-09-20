# Proximity Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable proximity service implementing Geohash radius search, Quadtree k-nearest search, business CRUD, two-level caching, and a `/compare` endpoint — in a single FastAPI process with SQLite + in-memory spatial indexes.

**Architecture:** Layered pure-logic modules (`geo`, `geohash`, `quadtree`) that are independently unit-testable, composed by `lbs_service` (read) and `business_service` (write) behind FastAPI routes. In-memory geohash map + quadtree are built at startup from the DB and maintained incrementally on writes.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, aiosqlite, Pydantic v2, stdlib `heapq`/`math`, pytest + pytest-asyncio + httpx TestClient.

**Spec reference:** `docs/superpowers/specs/2026-09-20-proximity-service-design.md`

---

### Task 1: Scaffolding & Config

**Files:**
- Create: `proximity-service/app/__init__.py`
- Create: `proximity-service/app/config.py`
- Create: `proximity-service/requirements.txt`

- [ ] **Step 1: Write `app/config.py`**

```python
"""Proximity Service Configuration — mirrors Chapter 16 design."""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProximityConfig:
    default_precision: int = 6        # ~±0.61km cell per chapter table
    default_radius_m: int = 5000      # 5km default search radius
    max_radius_m: int = 50000
    quadtree_capacity: int = 100      # per-node business cap before split
    quadtree_max_depth: int = 12
    cache_max_size: int = 1024

    data_dir: Path = field(default_factory=lambda: Path("data/proximity"))
    db_filename: str = "proximity.db"
    host: str = "0.0.0.0"
    port: int = 9300

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename
```

- [ ] **Step 2: Write `requirements.txt`** (same as google-drive: fastapi, uvicorn, aiosqlite, pydantic, httpx, pytest, pytest-asyncio)

- [ ] **Step 3: Create `app/__init__.py`** (empty comment line)

- [ ] **Step 4: Commit** `git commit -m 'feat(proximity): scaffolding and config'`

---

### Task 2: Geo Math Utilities

**Files:**
- Create: `proximity-service/app/geo.py`
- Create: `proximity-service/tests/test_geo.py`

- [ ] **Step 1: Write failing test** — haversine SF landmarks distance ≈ 1.4 km, bounding-box contains center.

```python
from app.geo import haversine_m, bounding_box

def test_haversine_known_distance():
    # Golden Gate Bridge to Ferry Building ≈ 6.9 km
    d = haversine_m(37.8199, -122.4783, 37.7955, -122.3937)
    assert 6000 < d < 8000

def test_bounding_box_contains_center():
    min_lat, max_lat, min_lng, max_lng = bounding_box(37.7749, -122.4194, 1000)
    assert min_lat < 37.7749 < max_lat
    assert min_lng < -122.4194 < max_lng
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Write `geo.py`**

```python
"""Pure geo math: Haversine distance + bounding box. Single source of truth for distance."""
import math

EARTH_RADIUS_M = 6371008.8


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in meters."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bounding_box(lat: float, lng: float, radius_m: float) -> tuple[float, float, float, float]:
    """Return (min_lat, max_lat, min_lng, max_lng) for a box around a point."""
    d_lat = math.degrees(radius_m / EARTH_RADIUS_M)
    # Guard against divide-by-zero at poles
    cos_lat = max(math.cos(math.radians(lat)), 1e-10)
    d_lng = math.degrees(radius_m / (EARTH_RADIUS_M * cos_lat))
    return (lat - d_lat, lat + d_lat, lng - d_lng, lng + d_lng)
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `git commit -m 'feat(proximity): geo math utilities'`

---

### Task 3: Geohash Encoding / Neighbors / Precision

**Files:**
- Create: `proximity-service/app/geohash.py`
- Create: `proximity-service/tests/test_geohash.py`

- [ ] **Step 1: Write failing tests**

```python
from app.geohash import encode, decode, neighbors, precision_for_radius

def test_encode_decode_round_trip():
    gh = encode(37.7749, -122.4194, 6)
    lat, lng, lat_err, lng_err = decode(gh)
    assert abs(lat - 37.7749) < lat_err * 2
    assert abs(lng - -122.4194) < lng_err * 2

def test_neighbors_returns_eight():
    n = neighbors("9q7")
    assert len(n) == 8
    assert "9q7" not in n

def test_precision_monotonic():
    assert precision_for_radius(150) >= precision_for_radius(5000)

def test_boundary_neighbors_capture_close_cells():
    # Two points sharing same center but at opposite edges of adjacent cells
    a = encode(37.7749, -122.4194, 6)
    ns = [a] + neighbors(a)
    b = encode(37.7750, -122.4193, 6)
    # b should be very close to a; both should be in neighbor set OR same cell
    assert b in ns or a == b
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Write `geohash.py`**

Implement:
- `_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"`
- `encode(lat, lng, precision)` — interleaves lng bits first (odd bits = longitude, even bits = latitude per standard geohash), groups into 5-bit chunks, base32-encodes.
- `decode(gh)` — returns center + half-width error in each dimension.
- `neighbors(gh)` — returns 8 adjacent cells by walking up/down/left/right using standard `NEIGHBOR_MAP`/`BORDER_MAP` tables (copy reference implementation from movable-type.co.uk geohash linked in chapter).
- `PRECISION_TABLE = {4: 39_000, 5: 4_900, 6: 1_200, 7: 153, 8: 19}` (km precision table from chapter).
- `precision_for_radius(m)` — returns smallest length L such that PRECISION_TABLE[L] >= m, clamped to [4, 8].

- [ ] **Step 4: Run test → PASS**

- [ ] **Step 5: Commit** `git commit -m 'feat(proximity): geohash encoding and neighbor calculation'`

---

### Task 4: Quadtree with k-Nearest

**Files:**
- Create: `proximity-service/app/quadtree.py`
- Create: `proximity-service/tests/test_quadtree.py`

- [ ] **Step 1: Write failing tests** — brute-force cross-validation of knn + radius query.

```python
import random
from app.quadtree import Quadtree, QuadPoint
from app.geo import haversine_m


def _brute_knn(points, lat, lng, k):
    scored = sorted(points, key=lambda p: haversine_m(lat, lng, p.lat, p.lng))
    return scored[:k]


def test_knn_matches_brute_force():
    random.seed(42)
    points = [QuadPoint(random.uniform(37.5, 38.0), random.uniform(-122.6, -122.2), i) for i in range(500)]
    qt = Quadtree((-180, -90, 180, 90), capacity=20, max_depth=10)
    for p in points:
        qt.insert(p)
    q_lat, q_lng = 37.7749, -122.4194
    got = qt.query_knn(q_lat, q_lng, 10)
    expected = _brute_knn(points, q_lat, q_lng, 10)
    assert [p.payload for p in got] == [p.payload for p in expected]


def test_query_radius_matches_brute_force():
    random.seed(43)
    points = [QuadPoint(37.7749 + random.uniform(-0.02, 0.02), -122.4194 + random.uniform(-0.02, 0.02), i) for i in range(100)]
    qt = Quadtree((-180, -90, 180, 90), capacity=20, max_depth=10)
    for p in points:
        qt.insert(p)
    r = 1500  # 1.5 km
    got = qt.query_radius(37.7749, -122.4194, r)
    expected = [p for p in points if haversine_m(37.7749, -122.4194, p.lat, p.lng) <= r]
    assert set(p.payload for p in got) == set(p.payload for p in expected)
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Write `quadtree.py`**

Dataclasses/classes:
- `QuadPoint(lat, lng, payload)` — hashable/equality by lat,lng,payload.
- `BBox(min_lng, min_lat, max_lng, max_lat)` — with `contains(lat,lng)` and `distance_to(lat,lng)` (0 if inside, else Haversine to closest edge).
- `QuadNode` — holds `bbox`, `points: list[QuadPoint]`, `children: list[QuadNode] | None`, `capacity`, `depth`, `max_depth`.
  - `insert(p)` — add; if len > capacity and depth < max_depth, split into 4 quadrants and redistribute; else stay (allow overflow at max depth for duplicates).
  - `query_radius(lat,lng,r)` — DFS; skip subtree if `bbox.distance_to > r`.
  - `query_knn(lat,lng,k)` — priority-first traversal using a min-heap of `(bbox_distance, node)` + max-heap of `(distance, point)` size k. Pop closest node, add its points, expand children with bbox_distance < current kth-worst.

- [ ] **Step 4: Run test → PASS**

- [ ] **Step 5: Commit** `git commit -m 'feat(proximity): quadtree with k-NN and radius queries'`

---

### Task 5: Database Layer (Businesses Table)

**Files:**
- Create: `proximity-service/app/database.py`
- Create: `proximity-service/app/models.py`

- [ ] **Step 1: Write `models.py`** — Pydantic `BusinessCreate`, `BusinessUpdate`, `Business(id, name, category, lat, lng, address, created_at)`, `SearchResult(business, distance_m)`, `KnnResult(items: list[SearchResult])`, `NearbyResult(items: list[SearchResult])`, `CompareResult(geohash, quadtree, ...)`

- [ ] **Step 2: Write `database.py`**
- Table: `businesses(id INTEGER PRIMARY KEY AUTOINCREMENT, name, category, lat, lng, address, created_at)`
- Async methods: `initialize()`, `insert(business)->id`, `get(id)`, `update(id, fields)`, `delete(id)`, `all()`, `count()`.

- [ ] **Step 3: Commit** `git commit -m 'feat(proximity): database and models'`

---

### Task 6: Two-Level LRU Cache

**Files:**
- Create: `proximity-service/app/cache.py`

- [ ] **Step 1: Write `cache.py`** — `class LRUCache(max_size)` using `collections.OrderedDict`. `get(k)`, `set(k,v)`, `invalidate(k)`. Two instances wrapped in a `CacheLayer` exposing `get_ids_by_geohash/set_ids_by_geohash/invalidate_geohash` and `get_business/set_business/invalidate_business`, with `hits`/`misses` counters.

- [ ] **Step 2: Commit** `git commit -m 'feat(proximity): two-level LRU cache'`

---

### Task 7: Business Service (Write Path)

**Files:**
- Create: `proximity-service/app/business_service.py`

- [ ] **Step 1: Write `business_service.py`** — owns DB, geohash_index (`dict[str, set[int]]`), quadtree, cache.

```python
class BusinessService:
    def __init__(self, config, db, geohash_index, quadtree, cache): ...

    async def create(self, req: BusinessCreate) -> int:
        # validate lat/lng range
        # insert into DB → id
        # gh = geohash.encode(lat, lng, config.default_precision)
        # geohash_index.setdefault(gh, set()).add(id)
        # quadtree.insert(QuadPoint(lat, lng, id))
        # cache.invalidate_geohash(gh); cache.invalidate_business(id)

    async def update(self, id: int, req: BusinessUpdate): ...
    async def delete(self, id: int): ...
    async def get(self, id: int) -> dict: ...
```

- [ ] **Step 2: Write `rebuild_indexes()`** — async startup helper: query all businesses, populate geohash_index + quadtree from scratch.

- [ ] **Step 3: Commit** `git commit -m 'feat(proximity): business service with index maintenance'`

---

### Task 8: Location-Based Service (Read Path)

**Files:**
- Create: `proximity-service/app/lbs_service.py`

- [ ] **Step 1: Write `lbs_service.py`**

```python
class LBSService:
    def __init__(self, config, db, geohash_index, quadtree, cache): ...

    async def search_nearby(self, lat, lng, radius_m) -> list[SearchResult]:
        # 1. precision = min(config.default_precision, geohash.precision_for_radius(radius_m))
        #    For simplicity: always use config.default_precision cells (union).
        # 2. center = geohash.encode(lat, lng, precision); cells = [center] + geohash.neighbors(center)
        # 3. For each cell: try cache.get_ids_by_geohash; on miss: gather ids from index, cache.set
        # 4. Union all candidate ids; for each, load details via cache.get_business/DB
        # 5. Filter haversine <= radius_m; sort ascending by distance

    async def search_knn(self, lat, lng, k) -> list[SearchResult]:
        # quadtree.query_knn → list of points sorted by distance
        # populate business details from cache/DB

    async def stats(self) -> dict: ...
```

- [ ] **Step 2: Commit** `git commit -m 'feat(proximity): LBS read path with geohash and quadtree searches'`

---

### Task 9: FastAPI Server Routes

**Files:**
- Create: `proximity-service/app/server.py`

- [ ] **Step 1: Wire endpoints**
- `POST /v1/businesses`, `GET/PUT/DELETE /v1/businesses/{id}`
- `GET /v1/search/nearby?lat&lng&radius` → returns list of `{business, distance_m}`
- `GET /v1/search/knn?lat&lng&k` → same shape
- `GET /v1/compare?lat&lng&radius&k` → time both, return `{geohash: {items, ms}, quadtree: {items, ms}}`
- `GET /v1/stats` → `{businesses, grids, cache_hits, cache_misses, quadtree_size}`
- Lifespan: init DB, build indexes, inject services.

- [ ] **Step 2: Commit** `git commit -m 'feat(proximity): FastAPI routes'`

---

### Task 10: CLI & Demo

**Files:**
- Create: `proximity-service/cli.py`
- Create: `proximity-service/__main__.py`

- [ ] **Step 1: `cli.py`** — subcommands: `add <name> <lat> <lng>`, `get <id>`, `delete <id>`, `nearby <lat> <lng> <radius>`, `knn <lat> <lng> <k>`, `compare <lat> <lng> <radius> <k>`, `stats`.

- [ ] **Step 2: `__main__.py`**
- `--server`: uvicorn
- `--demo`: in-process (no HTTP) — seed 30 businesses around SF, run radius search 500 m → print top-10 with distances; run knn=5; show a boundary-issue scenario (query at cell edge → neighbors rescue); run `/compare` and print both latencies; print stats.
- `--cli <args>`: forward to cli.

- [ ] **Step 3: Commit** `git commit -m 'feat(proximity): CLI and demo storyline'`

---

### Task 11: End-to-End Search Tests & README

**Files:**
- Create: `proximity-service/tests/conftest.py`
- Create: `proximity-service/tests/test_search.py`
- Create: `proximity-service/README.md`

- [ ] **Step 1: `tests/conftest.py`** — fixtures for a fresh `ProximityConfig(tmp_path)` + Database + geohash_index + quadtree + BusinessService + LBSService.

- [ ] **Step 2: `test_search.py`**

```python
@pytest.mark.asyncio
async def test_radius_search_returns_results_sorted_by_distance(business_svc, lbs_svc):
    await business_svc.create(BusinessCreate(name="A", category="cafe", lat=37.7749, lng=-122.4194, address="..."))
    await business_svc.create(BusinessCreate(name="B", category="cafe", lat=37.7760, lng=-122.4194, address="..."))
    results = await lbs_svc.search_nearby(37.7749, -122.4194, 2000)
    assert len(results) >= 2
    assert results[0].distance_m < results[1].distance_m

@pytest.mark.asyncio
async def test_knn_returns_k_results(business_svc, lbs_svc):
    for i in range(20):
        await business_svc.create(BusinessCreate(name=f"Biz{i}", category="x", lat=37.77 + i*0.001, lng=-122.41, address="..."))
    results = await lbs_svc.search_knn(37.77, -122.41, 5)
    assert len(results) == 5

@pytest.mark.asyncio
async def test_cache_hit_after_second_query(business_svc, lbs_svc, cache):
    await business_svc.create(BusinessCreate(name="C", category="x", lat=37.7749, lng=-122.4194, address="..."))
    initial_misses = cache.misses
    await lbs_svc.search_nearby(37.7749, -122.4194, 5000)
    await lbs_svc.search_nearby(37.7749, -122.4194, 5000)
    assert cache.hits > 0
```

- [ ] **Step 3: Run full test suite** — all pass.

- [ ] **Step 4: Write README.md** — features table mapping to chapter concepts, architecture diagram, quickstart (server/demo/cli), algorithm comparison summary, design decisions, out-of-scope.

- [ ] **Step 5: Update `.gitignore`** — add `proximity-service/data/`.

- [ ] **Step 6: Commit** `git commit -m 'feat(proximity): end-to-end tests and README'`

---

### Task 12: Run Demo End-to-End

- [ ] **Step 1: Execute demo**

```
cd proximity-service
python __main__.py --demo
```

Expected: seed 30 SF businesses → radius search prints top-10 by distance → knn=5 → boundary case rescued by neighbors → compare shows both algorithms' latency → stats prints cache hit rate.

- [ ] **Step 2: Confirm all tasks complete.**
