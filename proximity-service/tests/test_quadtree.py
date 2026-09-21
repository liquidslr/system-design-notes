"""Tests for Quadtree — validated against brute-force results."""
import random
from app.quadtree import Quadtree, QuadPoint
from app.geo import haversine_m


def _brute_knn(points, lat, lng, k):
    scored = sorted(points, key=lambda p: haversine_m(lat, lng, p.lat, p.lng))
    return scored[:k]


def test_knn_matches_brute_force():
    random.seed(42)
    points = [QuadPoint(random.uniform(37.5, 38.0), random.uniform(-122.6, -122.2), i)
              for i in range(500)]
    qt = Quadtree(capacity=20, max_depth=12)
    for p in points:
        qt.insert(p)
    q_lat, q_lng = 37.7749, -122.4194
    got = qt.query_knn(q_lat, q_lng, 10)
    expected = _brute_knn(points, q_lat, q_lng, 10)
    assert [p.payload for p in got] == [p.payload for p in expected]


def test_query_radius_matches_brute_force():
    random.seed(43)
    points = [QuadPoint(37.7749 + random.uniform(-0.02, 0.02),
                        -122.4194 + random.uniform(-0.02, 0.02), i)
              for i in range(200)]
    qt = Quadtree(capacity=20, max_depth=12)
    for p in points:
        qt.insert(p)
    r = 1500
    got = qt.query_radius(37.7749, -122.4194, r)
    expected = [p for p in points if haversine_m(37.7749, -122.4194, p.lat, p.lng) <= r]
    assert set(p.payload for p in got) == set(p.payload for p in expected)


def test_knn_ascending_distance():
    random.seed(7)
    qt = Quadtree(capacity=5, max_depth=10)
    for i in range(100):
        qt.insert(QuadPoint(37.7 + i * 0.001, -122.4, i))
    res = qt.query_knn(37.7, -122.4, 5)
    dists = [haversine_m(37.7, -122.4, p.lat, p.lng) for p in res]
    assert dists == sorted(dists)


def test_knn_handles_ties():
    # Duplicate coordinates must not raise (tuple-compare tiebreak)
    qt = Quadtree(capacity=2, max_depth=8)
    for i in range(10):
        qt.insert(QuadPoint(10.0, 20.0, i))
    res = qt.query_knn(10.0, 20.0, 5)
    assert len(res) == 5
