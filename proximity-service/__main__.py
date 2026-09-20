"""
Proximity Service — Entry Point

Usage:
    python __main__.py --server          # Run API server
    python __main__.py --demo            # Run in-process end-to-end demo
    python __main__.py --cli <args...>   # Forward to proximity-cli
"""
import argparse
import asyncio
import random
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import geohash as gh
from app.business_service import BusinessService, SpatialIndex
from app.cache import CacheLayer
from app.config import ProximityConfig
from app.database import Database
from app.lbs_service import LBSService
from app.models import BusinessCreate


# SF downtown seed data (name, category, lat, lng)
SF_SEED = [
    ("Ferry Building", "market", 37.7955, -122.3937),
    ("Bi-Rite Creamery", "ice-cream", 37.7614, -122.4350),
    ("Tartine Bakery", "bakery", 37.7614, -122.4350),
    ("Brenda's", "cafe", 37.7713, -122.4257),
    ("Blue Bottle", "cafe", 37.7720, -122.4140),
    ("Sightglass", "coffee", 37.7772, -122.4163),
    ("Wayfare", "cafe", 37.7848, -122.4055),
    ("Saison", "restaurant", 37.7719, -122.4218),
    ("Quince", "restaurant", 37.7963, -122.4007),
    ("Atelier Crenn", "restaurant", 37.8047, -122.4391),
    ("State Bird", "bar", 37.7654, -122.4211),
    ("The Trick", "bar", 37.7859, -122.4331),
    ("Barbarella", "bar", 37.7869, -122.4227),
    ("Vesuvio Cafe", "bar", 37.7969, -122.4059),
    ("Caffe Trippa", "cafe", 37.7628, -122.4351),
    ("Rainbow Bazaar", "market", 37.7664, -122.4393),
    ("Argus Coffee", "coffee", 37.7676, -122.4507),
    ("Ritual", "coffee", 37.7777, -122.4148),
    ("WreckRoom", "bar", 37.7699, -122.4097),
    ("Foreign Cinema", "restaurant", 37.7695, -122.4045),
    ("Gary Danko", "restaurant", 37.8032, -122.4227),
    ("Swan Oyster", "seafood", 37.8038, -122.4216),
    ("Hog Island", "seafood", 37.8043, -122.4194),
    ("Scoma's", "seafood", 37.8047, -122.3990),
    ("Angler", "restaurant", 37.7951, -122.3980),
    ("Nisei", "restaurant", 37.7943, -122.3983),
    ("Kokkari", "restaurant", 37.7651, -122.4289),
    ("Osteria", "restaurant", 37.7963, -122.4008),
    ("A16", "pizza", 37.7955, -122.3937),
    ("Golden Gate Park Deli", "deli", 37.7694, -122.4862),
]


def _hdr(text: str):
    print("\n" + text)
    print("  " + "-" * (len(text) - 2))


async def run_demo():
    print("=" * 66)
    print("  PROXIMITY SERVICE — DEMO  (Geohash radius + Quadtree k-NN)")
    print("=" * 66)

    demo_dir = Path("data/demo-run")
    if demo_dir.exists():
        shutil.rmtree(demo_dir)

    config = ProximityConfig()
    config.data_dir = demo_dir

    db = Database(config)
    await db.initialize()
    cache = CacheLayer(config.cache_max_size)
    index = SpatialIndex(config)
    business = BusinessService(config, db, index, cache)
    lbs = LBSService(config, db, index, cache)

    try:
        # [1] Seed 30 businesses around San Francisco
        _hdr("[1] Seeding 30 businesses around San Francisco")
        random.seed(7)
        for i in range(30):
            name, cat, lat, lng = SF_SEED[i]
            await business.create(BusinessCreate(
                name=name, category=cat, lat=lat, lng=lng, address=f"{cat} near {name}"))
        stats = await db.count()
        print(f"    ✓ {stats} businesses inserted")
        print(f"    Geohash grids populated : {index.grid_count}")
        print(f"    Quadtree points indexed : {len(index._coords)}")

        # [2] Geohash radius search
        _hdr("[2] Geohash radius search — 3 km around Salesforce Park (37.7848, -122.4055)")
        results = await lbs.search_nearby(37.7848, -122.4055, 3000)
        print(f"    {len(results)} businesses within 3 km (top 10 by distance):")
        for r in results[:10]:
            print(f"      {r.distance_m:>7.1f} m  {r.business.name:<22} [{r.business.category}]")

        # [3] Quadtree k-NN
        _hdr("[3] Quadtree k-NN search — 5 nearest to the same point")
        knn = await lbs.search_knn(37.7848, -122.4055, 5)
        for r in knn:
            print(f"      {r.distance_m:>7.1f} m  {r.business.name:<22} [{r.business.category}]")

        # [4] Boundary issue demonstration
        _hdr("[4] Geohash boundary issue — why we search center + 8 neighbors")
        # Query from a point close to a cell edge; a nearby business may fall in an
        # adjacent cell. Center-cell-only would miss it; the 8-neighbor union rescues it.
        q_lat, q_lng = 37.7897, -122.4095
        center = gh.encode(q_lat, q_lng, config.default_precision)
        # Brute-force nearest to this point:
        nearest = min(SF_SEED[:30], key=lambda s: _dist(q_lat, q_lng, s[2], s[3]))
        nearest_cell = gh.encode(nearest[2], nearest[3], config.default_precision)
        on_center = int(nearest_cell == center)
        rescued = int(nearest_cell in gh.neighbors(center))
        d = _dist(q_lat, q_lng, nearest[2], nearest[3])
        print(f"    Query cell          : {center}")
        print(f"    Nearest biz '{nearest[0]}' cell : {nearest_cell}  ({d:.0f} m away)")
        print(f"    Same cell as query? : {'YES' if on_center else 'no'}")
        print(f"    In 8 neighbors?     : {'YES — rescued by neighbor union!' if rescued and not on_center else ('n/a (same cell)' if on_center else 'no')}")
        only_center = 1 if on_center else 0
        with_neighbors = 1 if (on_center or rescued) else 0
        print(f"    Found w/ center only: {'YES' if only_center else 'NO (missed!)'}")
        print(f"    Found w/ + neighbors: {'YES' if with_neighbors else 'NO'}")

        # [5] Compare both algorithms
        _hdr("[5] Algorithm latency comparison (/v1/compare)")
        for _ in range(3):  # warm the cache
            await lbs.search_nearby(37.7848, -122.4055, 3000)
            await lbs.search_knn(37.7848, -122.4055, 10)
        t0 = time.perf_counter()
        geo_items = await lbs.search_nearby(37.7848, -122.4055, 3000)
        geo_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        qt_items = await lbs.search_knn(37.7848, -122.4055, 10)
        qt_ms = (time.perf_counter() - t0) * 1000
        print(f"    Geohash radius (3km): {len(geo_items):>3} results in {geo_ms:.3f} ms")
        print(f"    Quadtree k-NN (k=10): {len(qt_items):>3} results in {qt_ms:.3f} ms")

        # [6] Stats + cache hit rate
        _hdr("[6] System statistics & cache effectiveness")
        total = cache.hits + cache.misses
        rate = 100 * cache.hits / total if total else 0
        print(f"    Businesses     : {await db.count()}")
        print(f"    Geohash grids  : {index.grid_count}")
        print(f"    Quadtree points: {len(index._coords)}")
        print(f"    Cache hits     : {cache.hits}")
        print(f"    Cache misses   : {cache.misses}")
        print(f"    Cache hit rate : {rate:.1f}%")

        print("\n" + "=" * 66)
        print("  DEMO COMPLETE")
        print("=" * 66)
    finally:
        await db.close()


def _dist(lat1, lng1, lat2, lng2):
    from app.geo import haversine_m
    return haversine_m(lat1, lng1, lat2, lng2)


async def run_server():
    import uvicorn
    from app.server import app
    config = ProximityConfig()
    print(f"Starting Proximity Service on {config.host}:{config.port}")
    uvicorn.run(app, host=config.host, port=config.port)


def main():
    parser = argparse.ArgumentParser(description="Proximity Service")
    parser.add_argument("--server", action="store_true", help="Run API server")
    parser.add_argument("--demo", action="store_true", help="Run end-to-end demo")
    parser.add_argument("--cli", nargs=argparse.REMAINDER, help="Forward to proximity-cli")
    args = parser.parse_args()

    if args.server:
        asyncio.run(run_server())
    elif args.cli:
        sys.argv = ["proximity-cli"] + args.cli
        from cli import main as cli_main
        cli_main()
    else:
        asyncio.run(run_demo())


if __name__ == "__main__":
    main()
