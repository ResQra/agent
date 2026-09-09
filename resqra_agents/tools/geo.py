"""Pure-Python geo helpers for the standalone agent project."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

# Operational district bbox (mirrors backend/app/utils/geo.py).
RAUTAHAT_BBOX = (26.60, 85.13, 27.20, 85.47)


def in_operational_area(lat, lng) -> bool:
    """True when a point falls inside the district bbox."""
    try:
        sw_lat, sw_lng, ne_lat, ne_lng = RAUTAHAT_BBOX
        return sw_lat <= float(lat) <= ne_lat and sw_lng <= float(lng) <= ne_lng
    except (TypeError, ValueError):
        return False


# Text pre-filter mirror of backend/app/utils/geo.py (keep in sync).
# Intake's first look: obvious out-of-area text dies before any network,
# scoring, or downstream agent work is spent on it.
DISTRICT_KEYWORDS = (
    "rautahat", "gaur", "tikuliya", "garuda", "chandrapur", "chandranigahapur",
    "juddha", "bagmati", "lalbakaiya", "bairgania", "katahariya", "rajpur",
    "baudhimai", "rajdevi", "brindaban", "gadhimai", "madhesh",
    "ward no", "ward ",
)

FAR_PLACE_KEYWORDS = (
    "delhi", "new delhi", "mumbai", "kolkata", "calcutta", "chennai", "bangalore",
    "bengaluru", "hyderabad", "kathmandu", "lalitpur", "bhaktapur", "pokhara",
    "biratnagar", "janakpur", "dharan", "butwal", "nepalgunj", "dhangadhi",
    "patna", "bihar", "uttar pradesh", "jharkhand", "kolkata",
)


def jurisdiction_hint_from_text(text: str | None) -> str:
    """IN_DISTRICT | OUT_OF_DISTRICT | UNKNOWN — text only, no network."""
    import re

    lowered = f" {(text or '').lower()} "
    if any(re.search(rf"\b{re.escape(k)}\b", lowered) for k in DISTRICT_KEYWORDS):
        return "IN_DISTRICT"
    if any(re.search(rf"\b{re.escape(k)}\b", lowered) for k in FAR_PLACE_KEYWORDS):
        return "OUT_OF_DISTRICT"
    return "UNKNOWN"


def geohash_encode(lat: float, lng: float, precision: int = 6) -> str:
    """lat/lng -> geohash cell. Precision 6 is neighborhood scale (~1.2 km)."""
    lat_lo, lat_hi = -90.0, 90.0
    lng_lo, lng_hi = -180.0, 180.0
    bits = [16, 8, 4, 2, 1]
    chars: list[str] = []
    ch = 0
    bit = 0
    even = True
    while len(chars) < precision:
        if even:
            mid = (lng_lo + lng_hi) / 2
            if lng >= mid:
                ch |= bits[bit]
                lng_lo = mid
            else:
                lng_hi = mid
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                ch |= bits[bit]
                lat_lo = mid
            else:
                lat_hi = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            chars.append(_BASE32[ch])
            bit = 0
            ch = 0
    return "".join(chars)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


SHELTER_RADIUS_M = 250


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def nearest_open_shelter(location: dict | None, shelters: list | None,
                         radius_m: float = SHELTER_RADIUS_M) -> dict | None:
    """Nearest OPEN shelter with free beds inside radius_m of location.

    Returns {shelter, distance_m, free} or None. Pure + deterministic —
    shared by priority (safety-perimeter factor) and allocation
    (shelter-in-place option). No DB, no network.
    """
    if not location or not shelters:
        return None
    lat, lng = _num(location.get("lat")), _num(location.get("lng"))
    if lat is None or lng is None:
        return None
    best = None
    for s in shelters:
        sloc = (s or {}).get("location") or {}
        slat, slng = _num(sloc.get("lat")), _num(sloc.get("lng"))
        if slat is None or slng is None:
            continue
        if str(s.get("status", "OPEN")).upper() not in ("OPEN", "AVAILABLE"):
            continue
        free = max(0, int(s.get("capacity") or 0) - int(s.get("current_occupancy") or 0))
        if free <= 0:
            continue
        dist_m = haversine_km(lat, lng, slat, slng) * 1000
        if dist_m <= radius_m and (best is None or dist_m < best["distance_m"]):
            best = {"shelter": s, "distance_m": round(dist_m, 1), "free": free}
    return best
