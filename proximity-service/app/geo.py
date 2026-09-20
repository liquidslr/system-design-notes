"""Pure geo math: Haversine distance + bounding box. Single source of truth for distance."""
import math

EARTH_RADIUS_M = 6371008.8


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS-84 points in meters."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bounding_box(lat: float, lng: float, radius_m: float) -> tuple[float, float, float, float]:
    """Return (min_lat, max_lat, min_lng, max_lng) for a box around a point."""
    d_lat = math.degrees(radius_m / EARTH_RADIUS_M)
    cos_lat = max(abs(math.cos(math.radians(lat))), 1e-10)
    d_lng = math.degrees(radius_m / (EARTH_RADIUS_M * cos_lat))
    return (lat - d_lat, lat + d_lat, lng - d_lng, lng + d_lng)
