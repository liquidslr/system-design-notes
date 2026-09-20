"""Tests for geo math utilities."""
from app.geo import haversine_m, bounding_box


def test_haversine_known_distance():
    # Golden Gate Bridge to Ferry Building ≈ 6.9 km
    d = haversine_m(37.8199, -122.4783, 37.7955, -122.3937)
    assert 6000 < d < 8000


def test_haversine_zero():
    assert haversine_m(37.7749, -122.4194, 37.7749, -122.4194) == 0


def test_bounding_box_contains_center():
    min_lat, max_lat, min_lng, max_lng = bounding_box(37.7749, -122.4194, 1000)
    assert min_lat < 37.7749 < max_lat
    assert min_lng < -122.4194 < max_lng
