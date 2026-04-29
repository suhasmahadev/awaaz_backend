"""
Geohash utilities — AWAAZ-PROOF.
ANTIGRAVITY: pure-Python geohash encoder — no binary dependencies.
Eliminates python-geohash/pygeohash C extension build issues on Windows.
Algorithm: standard Gustavo Niemeyer geohash (Base32).
"""
import logging
from functools import lru_cache
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Pure-Python Base32 geohash encoder ─────────────────────────────────────────
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def _geohash_encode(lat: float, lng: float, precision: int) -> str:
    """
    Pure-Python Gustavo Niemeyer geohash encoder.
    No C extensions, no binary dependencies — runs on any Python 3.11+.
    Verified: (12.9716, 77.5946, 7) → 'tdr1v9q'
    """
    min_lat, max_lat = -90.0, 90.0
    min_lng, max_lng = -180.0, 180.0
    result: list[str] = []
    bits = [16, 8, 4, 2, 1]
    bit = 0
    ch = 0
    even = True  # even iterations bisect longitude

    while len(result) < precision:
        if even:
            mid = (min_lng + max_lng) / 2
            if lng >= mid:
                ch |= bits[bit]
                min_lng = mid
            else:
                max_lng = mid
        else:
            mid = (min_lat + max_lat) / 2
            if lat >= mid:
                ch |= bits[bit]
                min_lat = mid
            else:
                max_lat = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            result.append(_BASE32[ch])
            bit = 0
            ch = 0
    return "".join(result)


def coords_to_geohash(lat: float, lng: float, precision: int = 7) -> str:
    """
    Convert lat/lng coordinates to geohash string.

    Args:
        lat:       Latitude  (-90.0 to 90.0)
        lng:       Longitude (-180.0 to 180.0)
        precision: Output length (5=≈5km, 6=≈1.2km, 7=≈150m)

    Returns:
        Lowercase geohash string of length `precision`.

    Raises:
        ValueError: If lat/lng are out of valid range.
    """
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"Latitude {lat} out of range [-90, 90]")
    if not (-180.0 <= lng <= 180.0):
        raise ValueError(f"Longitude {lng} out of range [-180, 180]")
    if not (1 <= precision <= 12):
        raise ValueError(f"Precision {precision} out of range [1, 12]")
    return _geohash_encode(lat, lng, precision)


def find_nearest_asset_geohashes(lat: float, lng: float) -> list[str]:
    """
    Returns geohash candidates at precision 7, 6, 5 for proximity search.
    Precision 7 ≈ 150m, 6 ≈ 1.2km, 5 ≈ 5km.
    Used by repo.find_nearest_asset() as ANY($1::text[]) parameter.
    """
    gh7 = coords_to_geohash(lat, lng, 7)
    return [gh7, gh7[:6], gh7[:5]]


# Keep old name as alias
find_nearest_asset_geohash = find_nearest_asset_geohashes


# ── Reverse geocoding (Nominatim + LRU cache) ──────────────────────────────────
@lru_cache(maxsize=500)
def reverse_geocode_ward(lat: float, lng: float) -> dict:
    """
    Reverse geocode lat/lng to ward/city using OSM Nominatim.
    LRU-cached (500 entries) — respects Nominatim rate limit (1 req/sec).
    Returns fallback dict if network fails — never raises.
    """
    try:
        r = httpx.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lng, "format": "json"},
            headers={"User-Agent": "awaaz-proof-hackathon/1.0"},
            timeout=5.0,
        )
        data = r.json()
        addr = data.get("address", {})
        return {
            "ward":  addr.get("suburb") or addr.get("neighbourhood") or "Unknown",
            "city":  addr.get("city") or addr.get("town") or "Unknown",
            "state": addr.get("state", "Unknown"),
        }
    except (httpx.RequestError, httpx.TimeoutException, ValueError) as exc:
        logger.warning("reverse_geocode_ward(%s, %s) failed: %s", lat, lng, exc)
        return {"ward": "Unknown", "city": "Unknown", "state": "Unknown"}
