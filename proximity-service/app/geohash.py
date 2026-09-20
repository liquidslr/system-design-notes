"""
Geohash: encode/decode lat/lng into a single string that preserves proximity.
Reference: https://www.movable-type.co.uk/scripts/geohash.html (chapter's link).

Standard geohash: interleave longitude then latitude bits (lon is the "even"/first bit),
group 5 bits per character, base32 alphabet (no a, i, l, o).
"""
from __future__ import annotations

# Standard geohash base32 alphabet (excludes a, i, l, o for legibility).
BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_B32_IDX = {c: i for i, c in enumerate(BASE32)}

# Chapter's radius -> precision table (approx cell edge length in meters).
# Key = geohash string length, Value = approximate N/S precision in meters.
PRECISION_TABLE: dict[int, int] = {
    1: 5_000_000, 2: 500_000, 3: 150_000, 4: 39_000, 5: 4_900,
    6: 1_200, 7: 153, 8: 19, 9: 2, 10: 0.24,  # type: ignore
}


def encode(lat: float, lng: float, precision: int = 6) -> str:
    """Encode WGS-84 coordinates into a geohash string of the requested length."""
    if not -90 <= lat <= 90:
        raise ValueError(f"lat out of range: {lat}")
    if not -180 <= lng <= 180:
        raise ValueError(f"lng out of range: {lng}")

    lat_range = [-90.0, 90.0]
    lng_range = [-180.0, 180.0]
    bits = []
    is_lon = True  # longitude bit comes first

    while len(bits) < precision * 5:
        if is_lon:
            mid = (lng_range[0] + lng_range[1]) / 2
            if lng >= mid:
                bits.append(1)
                lng_range[0] = mid
            else:
                bits.append(0)
                lng_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat >= mid:
                bits.append(1)
                lat_range[0] = mid
            else:
                bits.append(0)
                lat_range[1] = mid
        is_lon = not is_lon

    # Pack 5-bit groups into base32 characters.
    out = []
    for i in range(0, len(bits), 5):
        v = 0
        for b in bits[i:i + 5]:
            v = (v << 1) | b
        out.append(BASE32[v])
    return "".join(out)


def decode(gh: str) -> tuple[float, float, float, float]:
    """Decode a geohash to (center_lat, center_lng, lat_err, lng_err)."""
    # Reconstruct interleaved bit stream
    bits = []
    for c in gh:
        v = _B32_IDX[c]
        for i in range(4, -1, -1):
            bits.append((v >> i) & 1)

    lat_range = [-90.0, 90.0]
    lng_range = [-180.0, 180.0]
    is_lon = True
    for b in bits:
        if is_lon:
            mid = (lng_range[0] + lng_range[1]) / 2
            # b=1 -> point in upper half -> raise lower bound; b=0 -> lower upper bound
            if b:
                lng_range[0] = mid
            else:
                lng_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if b:
                lat_range[0] = mid
            else:
                lat_range[1] = mid
        is_lon = not is_lon

    lat_c = (lat_range[0] + lat_range[1]) / 2
    lng_c = (lng_range[0] + lng_range[1]) / 2
    lat_err = (lat_range[1] - lat_range[0]) / 2
    lng_err = (lng_range[1] - lng_range[0]) / 2
    return lat_c, lng_c, lat_err, lng_err


# --- Neighbor computation (solves the chapter's "boundary issue") ---
# Robust approach: decode the cell to its center + half-extents, then step one
# full cell width in each direction and re-encode at the same precision. This
# avoids the fragile character-substitution neighbor tables.


def _adjacent(gh: str, dlat: float, dlng: float) -> str:
    """Return the geohash of the cell offset by (dlat, dlng) cell steps."""
    lat, lng, lat_err, lng_err = decode(gh)
    # lat_err/lng_err are half-widths; a full cell step is 2 * err.
    new_lat = lat + dlat * (2 * lat_err)
    new_lng = lng + dlng * (2 * lng_err)
    new_lat = max(-90.0, min(90.0, new_lat))
    new_lng = max(-180.0, min(180.0, new_lng))
    return encode(new_lat, new_lng, len(gh))


def neighbors(gh: str) -> list[str]:
    """Return the 8 adjacent geohash cells (N, S, E, W, and 4 diagonals)."""
    return [
        _adjacent(gh, 1, 0),    # top
        _adjacent(gh, -1, 0),   # bottom
        _adjacent(gh, 0, 1),    # right
        _adjacent(gh, 0, -1),   # left
        _adjacent(gh, 1, 1),    # top-right
        _adjacent(gh, 1, -1),   # top-left
        _adjacent(gh, -1, 1),   # bottom-right
        _adjacent(gh, -1, -1),  # bottom-left
    ]


def precision_for_radius(radius_m: float) -> int:
    """Return the smallest geohash length whose cell is <= radius (chapter's table)."""
    if radius_m <= 0:
        return 10
    # Choose the largest length whose precision is still >= radius (min cost).
    best = 1
    for length in sorted(PRECISION_TABLE):
        if PRECISION_TABLE[length] >= radius_m:
            best = length
            break
    else:
        # radius larger than the coarsest bucket; clamp to 1 char
        best = 1
    # We want the cell to be no larger than the radius, so step one finer.
    return min(10, best + 1) if best >= 1 else best
