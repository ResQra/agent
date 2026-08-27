"""Weather service — fetches current weather + 24h forecast from Open-Meteo.

Open-Meteo is free, no API key required, and covers the entire globe.
Results are cached for 10 minutes per coordinate pair.

Used by the agent to provide weather context (rain, wind, temperature)
for disaster response decisions.
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.parse

_CACHE_TTL_S = 10 * 60  # 10 minutes
_cache: dict[str, tuple[float, dict]] = {}


def _coord_key(lat: float, lng: float) -> str:
    return f"{lat:.4f},{lng:.4f}"


def _fetch_weather(lat: float, lng: float) -> dict | None:
    """Fetch current + 24h forecast from Open-Meteo."""
    params = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lng,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,precipitation",
        "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m",
        "forecast_days": 1,
        "timezone": "auto",
    })
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ResQra/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


WMO_CODES = {
    0: "clear", 1: "mainly_clear", 2: "partly_cloudy", 3: "overcast",
    45: "fog", 48: "rime_fog",
    51: "light_drizzle", 53: "moderate_drizzle", 55: "dense_drizzle",
    61: "slight_rain", 63: "moderate_rain", 65: "heavy_rain",
    71: "slight_snow", 73: "moderate_snow", 75: "heavy_snow",
    80: "slight_rain_showers", 81: "moderate_rain_showers", 82: "violent_rain_showers",
    95: "thunderstorm", 96: "thunderstorm_with_hail", 99: "thunderstorm_with_heavy_hail",
}


def get_weather(lat: float, lng: float) -> dict:
    """Return current weather + next 24h summary for a coordinate.

    Returns:
        {
            "current": {"temp_c": 28.5, "humidity_pct": 85, "wind_kmh": 12,
                         "condition": "moderate_rain", "precipitation_mm": 2.1},
            "hourly": [{"hour": "14:00", "temp_c": 29, "precip_prob": 80,
                         "precip_mm": 3.5, "wind_kmh": 15}, ...],
            "flood_risk": "high" | "moderate" | "low",
            "summary": "Heavy rain expected in the next 6 hours..."
        }
    """
    key = _coord_key(lat, lng)
    now = time.time()

    # Cache check
    if key in _cache:
        cached_at, cached_data = _cache[key]
        if now - cached_at < _CACHE_TTL_S:
            return cached_data

    raw = _fetch_weather(lat, lng)
    if raw is None:
        return {"error": "weather_unavailable", "current": {}, "hourly": [], "flood_risk": "unknown", "summary": "Weather data unavailable."}

    current = raw.get("current", {})
    hourly_data = raw.get("hourly", {})
    hours = hourly_data.get("time", [])
    temps = hourly_data.get("temperature_2m", [])
    precip_probs = hourly_data.get("precipitation_probability", [])
    precip_mm = hourly_data.get("precipitation", [])
    winds = hourly_data.get("wind_speed_10m", [])

    # Build hourly forecast (next 24h)
    hourly = []
    total_precip = 0.0
    max_prob = 0
    for i in range(min(24, len(hours))):
        h = hours[i] if i < len(hours) else "?"
        t = temps[i] if i < len(temps) else None
        pp = precip_probs[i] if i < len(precip_probs) else 0
        pm = precip_mm[i] if i < len(precip_mm) else 0
        w = winds[i] if i < len(winds) else None
        total_precip += pm or 0
        max_prob = max(max_prob, pp or 0)
        hourly.append({
            "hour": h.split("T")[-1] if "T" in str(h) else str(h),
            "temp_c": t,
            "precip_prob": pp,
            "precip_mm": pm,
            "wind_kmh": w,
        })

    # Flood risk assessment
    weather_code = current.get("weather_code", 0)
    condition = WMO_CODES.get(weather_code, "unknown")
    current_precip = current.get("precipitation", 0) or 0

    if total_precip > 20 or current_precip > 5 or condition in ("heavy_rain", "violent_rain_showers", "thunderstorm", "thunderstorm_with_hail", "thunderstorm_with_heavy_hail"):
        flood_risk = "high"
    elif total_precip > 8 or current_precip > 2 or condition in ("moderate_rain", "heavy_drizzle", "dense_drizzle"):
        flood_risk = "moderate"
    else:
        flood_risk = "low"

    # Summary
    summary_parts = []
    if current_precip > 0:
        summary_parts.append(f"Currently raining ({current_precip:.1f}mm)")
    if total_precip > 0:
        summary_parts.append(f"{total_precip:.1f}mm expected in next 24h")
    if flood_risk == "high":
        summary_parts.append("HIGH flood risk — monitor water levels closely")
    elif flood_risk == "moderate":
        summary_parts.append("Moderate flood risk — stay alert")
    if not summary_parts:
        summary_parts.append("No significant precipitation expected")

    result = {
        "current": {
            "temp_c": current.get("temperature_2m"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "wind_kmh": current.get("wind_speed_10m"),
            "condition": condition,
            "precipitation_mm": current_precip,
        },
        "hourly": hourly,
        "flood_risk": flood_risk,
        "total_precip_24h_mm": round(total_precip, 1),
        "max_precip_prob_pct": max_prob,
        "summary": ". ".join(summary_parts) + ".",
    }

    _cache[key] = (now, result)
    return result
