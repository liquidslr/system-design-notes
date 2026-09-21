"""
Quadtree spatial index — recursively divides 2D space into 4 quadrants.
Per chapter: built at startup, supports k-nearest and radius queries efficiently.
Pure in-memory structure, no I/O.

Coordinate space is treated as planar lat/lng for subdivision; all distance
comparisons use haversine for accuracy (approximation is fine for pruning).
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from .geo import haversine_m


@dataclass
class QuadPoint:
    lat: float
    lng: float
    payload: object = None

    def distance_m(self, lat: float, lng: float) -> float:
        return haversine_m(self.lat, self.lng, lat, lng)


@dataclass
class BBox:
    """A lat/lng rectangle. min_lat <= max_lat, min_lng <= max_lng."""
    min_lng: float
    min_lat: float
    max_lng: float
    max_lat: float

    def contains(self, lat: float, lng: float) -> bool:
        return self.min_lat <= lat <= self.max_lat and self.min_lng <= lng <= self.max_lng

    def distance_to(self, lat: float, lng: float) -> float:
        """Lower bound on distance from a point to anything in this box (meters)."""
        cl_lat = min(max(lat, self.min_lat), self.max_lat)
        cl_lng = min(max(lng, self.min_lng), self.max_lng)
        return haversine_m(lat, lng, cl_lat, cl_lng)

    def split(self) -> tuple[BBox, BBox, BBox, BBox]:
        mlat = (self.min_lat + self.max_lat) / 2
        mlng = (self.min_lng + self.max_lng) / 2
        return (
            BBox(self.min_lng, self.min_lat, mlng, mlat),  # SW
            BBox(mlng, self.min_lat, self.max_lng, mlat),  # SE
            BBox(self.min_lng, mlat, mlng, self.max_lat),  # NW
            BBox(mlng, mlat, self.max_lng, self.max_lat),  # NE
        )


WORLD = BBox(-180.0, -90.0, 180.0, 90.0)


@dataclass
class QuadNode:
    bbox: BBox
    capacity: int
    depth: int
    max_depth: int
    points: list[QuadPoint] = field(default_factory=list)
    children: list[QuadNode] | None = None

    def insert(self, p: QuadPoint) -> None:
        if self.children is not None:
            for c in self.children:
                if c.bbox.contains(p.lat, p.lng):
                    c.insert(p)
                    return
            # On bbox boundary of a child edge case: store here
            self.points.append(p)
            return

        self.points.append(p)
        if len(self.points) > self.capacity and self.depth < self.max_depth:
            self._subdivide()

    def _subdivide(self) -> None:
        self.children = [QuadNode(b, self.capacity, self.depth + 1, self.max_depth)
                         for b in self.bbox.split()]
        remaining: list[QuadPoint] = []
        for pt in self.points:
            placed = False
            for c in self.children:
                if c.bbox.contains(pt.lat, pt.lng):
                    c.points.append(pt)
                    placed = True
                    break
            if not placed:
                remaining.append(pt)
        self.points = remaining


class Quadtree:
    def __init__(self, bbox: BBox = WORLD, capacity: int = 100, max_depth: int = 12):
        if isinstance(bbox, tuple):  # allow (min_lng,min_lat,max_lng,max_lat)
            bbox = BBox(*bbox)
        self.root = QuadNode(bbox, capacity, 0, max_depth)

    def insert(self, p: QuadPoint) -> None:
        self.root.insert(p)

    def query_radius(self, lat: float, lng: float, radius_m: float) -> list[QuadPoint]:
        """All points within radius_m, unordered."""
        out: list[QuadPoint] = []
        self._radius_collect(self.root, lat, lng, radius_m, out)
        return out

    def _radius_collect(self, node: QuadNode, lat, lng, r, out) -> None:
        if node.bbox.distance_to(lat, lng) > r:
            return
        for p in node.points:
            if p.distance_m(lat, lng) <= r:
                out.append(p)
        if node.children:
            for c in node.children:
                self._radius_collect(c, lat, lng, r, out)

    def query_knn(self, lat: float, lng: float, k: int) -> list[QuadPoint]:
        """
        k nearest points, ascending by distance. Best-first traversal with
        bbox pruning: a min-heap of nodes keyed by bbox distance; a max-heap
        (negated) of the current best k points.
        """
        if k <= 0:
            return []
        # node heap: (bbox_dist, tie, node)
        node_heap: list[tuple[float, int, QuadNode]] = [(self.root.bbox.distance_to(lat, lng), 0, self.root)]
        # best heap: (-dist, tie, point) keeps k closest; largest at top for eviction.
        # The int tiebreaker avoids comparing QuadPoint objects on distance ties.
        best: list[tuple[float, int, QuadPoint]] = []
        tie = 1
        seq = 1

        while node_heap:
            ndist, _, node = heapq.heappop(node_heap)
            # If we already have k points and the closest possible in this node is
            # farther than our current k-th best, we can stop entirely.
            if len(best) >= k and ndist > -best[0][0]:
                break
            for p in node.points:
                d = p.distance_m(lat, lng)
                if len(best) < k:
                    heapq.heappush(best, (-d, seq, p))
                    seq += 1
                elif d < -best[0][0]:
                    heapq.heapreplace(best, (-d, seq, p))
                    seq += 1
            if node.children:
                for c in node.children:
                    cd = c.bbox.distance_to(lat, lng)
                    if len(best) < k or cd <= -best[0][0]:
                        heapq.heappush(node_heap, (cd, tie, c))
                        tie += 1

        results = [p for _, _, p in best]
        results.sort(key=lambda p: p.distance_m(lat, lng))
        return results
