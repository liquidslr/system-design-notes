"""
proximity-cli — Command-line client for the Proximity Service.
Usage: python cli.py <command> [args...]
Requires a running server (python __main__.py --server).
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

BASE_URL = os.environ.get("PROXIMITY_SERVER", "http://127.0.0.1:9300")


def _out(data) -> None:
    import json
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ─── Business CRUD ────────────────────────────────────────────────────

def cmd_add(args):
    payload = {"name": args.name, "lat": args.lat, "lng": args.lng,
               "category": args.category, "address": args.address}
    r = httpx.post(f"{BASE_URL}/v1/businesses", json=payload)
    if r.status_code == 201:
        print(f"Created business id={r.json()['id']}")
    else:
        print(f"Error: {r.json()}")


def cmd_get(args):
    r = httpx.get(f"{BASE_URL}/v1/businesses/{args.id}")
    _out(r.json()) if r.status_code == 200 else print(f"Error: {r.json()}")


def cmd_delete(args):
    r = httpx.delete(f"{BASE_URL}/v1/businesses/{args.id}")
    print(r.json() if r.status_code == 200 else f"Error: {r.json()}")


# ─── Search ───────────────────────────────────────────────────────────

def _print_results(items: list[dict]):
    if not items:
        print("  (no results)")
        return
    print(f"  {'DIST(m)':<10} {'ID':<5} {'NAME':<24} CATEGORY")
    print("  " + "-" * 55)
    for it in items:
        b = it["business"]
        print(f"  {it['distance_m']:<10.1f} {b['id']:<5} {b['name']:<24} {b['category']}")


def cmd_nearby(args):
    params = {"lat": args.lat, "lng": args.lng, "radius": args.radius}
    r = httpx.get(f"{BASE_URL}/v1/search/nearby", params=params)
    data = r.json()
    print(f"Nearby ({data['radius_m']:.0f} m) around ({args.lat}, {args.lng}): {len(data['items'])} hits")
    _print_results(data["items"])


def cmd_knn(args):
    params = {"lat": args.lat, "lng": args.lng, "k": args.k}
    r = httpx.get(f"{BASE_URL}/v1/search/knn", params=params)
    data = r.json()
    print(f"{data['k']} nearest around ({args.lat}, {args.lng}):")
    _print_results(data["items"])


def cmd_compare(args):
    params = {"lat": args.lat, "lng": args.lng, "radius": args.radius, "k": args.k}
    r = httpx.get(f"{BASE_URL}/v1/compare", params=params)
    d = r.json()
    print(f"Geohash radius search : {len(d['geohash']['items']):>3} results in {d['geohash']['ms']:.3f} ms")
    print(f"Quadtree k-NN search  : {len(d['quadtree']['items']):>3} results in {d['quadtree']['ms']:.3f} ms")


def cmd_stats(args):
    r = httpx.get(f"{BASE_URL}/v1/stats")
    d = r.json()
    total = d["cache_hits"] + d["cache_misses"]
    rate = 100 * d["cache_hits"] / total if total else 0
    print(f"  Businesses     : {d['businesses']}")
    print(f"  Geohash grids  : {d['grids']}")
    print(f"  Quadtree points: {d['quadtree_points']}")
    print(f"  Cache hits     : {d['cache_hits']}")
    print(f"  Cache misses   : {d['cache_misses']}")
    print(f"  Cache hit rate : {rate:.1f}%")


def main():
    parser = argparse.ArgumentParser(prog="proximity-cli", description="Proximity Service CLI")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("add", help="Add a business")
    p.add_argument("name"); p.add_argument("lat", type=float); p.add_argument("lng", type=float)
    p.add_argument("--category", default="general"); p.add_argument("--address", default="")

    p = sub.add_parser("get", help="Get a business by id")
    p.add_argument("id", type=int)

    p = sub.add_parser("delete", help="Delete a business by id")
    p.add_argument("id", type=int)

    p = sub.add_parser("nearby", help="Radius search (geohash)")
    p.add_argument("lat", type=float); p.add_argument("lng", type=float)
    p.add_argument("radius", type=float, nargs="?", default=5000)

    p = sub.add_parser("knn", help="k-nearest search (quadtree)")
    p.add_argument("lat", type=float); p.add_argument("lng", type=float)
    p.add_argument("k", type=int, nargs="?", default=10)

    p = sub.add_parser("compare", help="Compare both algorithms' latency")
    p.add_argument("lat", type=float); p.add_argument("lng", type=float)
    p.add_argument("radius", type=float, nargs="?", default=5000)
    p.add_argument("k", type=int, nargs="?", default=10)

    sub.add_parser("stats", help="Show system stats")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    cmds = {
        "add": cmd_add, "get": cmd_get, "delete": cmd_delete,
        "nearby": cmd_nearby, "knn": cmd_knn, "compare": cmd_compare, "stats": cmd_stats,
    }
    try:
        cmds[args.command](args)
    except httpx.ConnectError:
        print(f"Cannot reach server at {BASE_URL}. Start it with: python __main__.py --server")
        sys.exit(1)


if __name__ == "__main__":
    main()
