"""Tests for geohash encode/decode/neighbors/precision."""
from app.geohash import encode, decode, neighbors, precision_for_radius


def test_encode_decode_round_trip():
    gh = encode(37.7749, -122.4194, 6)
    lat, lng, lat_err, lng_err = decode(gh)
    assert abs(lat - 37.7749) <= lat_err + 1e-4
    assert abs(lng - (-122.4194)) <= lng_err + 1e-4


def test_encode_length_matches_precision():
    assert len(encode(0.0, 0.0, 5)) == 5
    assert len(encode(0.0, 0.0, 8)) == 8


def test_encode_known_reference():
    # San Francisco downtown (~37.7749, -122.4194) has a well-known geohash '9q8...'
    gh = encode(37.7749, -122.4194, 6)
    assert gh.startswith("9q8")


def test_neighbors_returns_eight_distinct():
    center = encode(37.7749, -122.4194, 6)
    n = neighbors(center)
    assert len(n) == 8
    assert len(set(n)) == 8
    assert center not in n


def test_neighbor_is_symmetric():
    # The center should be a neighbor of one of its neighbors (adjacency is reciprocal)
    center = encode(37.7749, -122.4194, 6)
    for nb in neighbors(center):
        if center in neighbors(nb):
            break
    else:
        raise AssertionError("no reciprocal neighbor found")


def test_precision_monotonic():
    # smaller radius => finer (larger) precision length
    assert precision_for_radius(150) >= precision_for_radius(5000)


def test_boundary_neighbors_capture_close_cell():
    # A point just across a cell boundary should appear among center's neighbors
    center = encode(37.7749, -122.4194, 6)
    cells = [center] + neighbors(center)
    # A point ~100m east, potentially in an adjacent cell
    near = encode(37.7749, -122.4183, 6)
    assert near in cells
