"""Deterministic incident priority scoring."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any


URGENCY_POINTS = {
    "CRITICAL": 6,
    "HIGH": 4,
    "MEDIUM": 2,
    "LOW": 0,
    "UNKNOWN": 2,
}

AREA_POINTS = {"HOTSPOT": 2, "RISING": 1, "NORMAL": 0}
RIVER_POINTS = {"SEVERE": 2, "ELEVATED": 1, "NORMAL": 0}
PRIORITY_BANDS = [("CRITICAL", 12), ("HIGH", 8), ("MEDIUM", 4)]

PEOPLE_DIVISOR = 3
PEOPLE_CAP = 4
VULN_POINTS_PER_TYPE = 2
VULN_TYPE_CAP = 2
WAITING_MINUTES_PER_POINT = 20
WAITING_CAP = 3


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _created_at_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def waiting_minutes(created_at: Any, now: float | None = None) -> int:
    created = _created_at_seconds(created_at)
    if created is None:
        return 0
    current = now if now is not None else time.time()
    return max(0, int((current - created) // 60))


def _incident_factors(incident: dict) -> dict:
    extraction = incident.get("extraction") or {}
    people = (
        extraction.get("people_count")
        if extraction.get("people_count") is not None
        else incident.get("people")
    )
    vulnerabilities = (
        extraction.get("vulnerabilities")
        if extraction.get("vulnerabilities") is not None
        else incident.get("vulnerabilities")
    )
    urgency = extraction.get("urgency") or incident.get("urgency") or "UNKNOWN"
    return {
        "people_count": people,
        "vulnerabilities": vulnerabilities or [],
        "urgency": str(urgency).upper(),
    }


def compute_priority(
    incident: dict,
    area: dict | None = None,
    weather: dict | None = None,
    now: float | None = None,
    shelters: list | None = None,
) -> dict:
    # Jurisdiction guard: outside the operational district this is not a
    # rescue-queue emergency. Score 0 with the reason on record instead of
    # letting spam compete with real district SOS.
    if (incident or {}).get("out_of_area"):
        return {
            "score": 0,
            "band": "LOW",
            "factors": [{"name": "jurisdiction", "points": 0,
                         "reason": "outside operational district (Rautahat) — "
                                   "routed to review, not the rescue queue"}],
            "reasons": ["outside operational district (Rautahat) — "
                        "routed to review, not the rescue queue"],
        }
    extracted = _incident_factors(incident or {})
    factors: list[dict] = []

    def add(name: str, points: int, reason: str) -> None:
        factors.append({"name": name, "points": points, "reason": reason})

    urgency = extracted["urgency"]
    if urgency not in URGENCY_POINTS:
        urgency = "UNKNOWN"
    points = URGENCY_POINTS[urgency]
    if urgency == "UNKNOWN":
        add("urgency", points, "urgency unknown, treated as medium (+2)")
    else:
        add("urgency", points, f"urgency {urgency} (+{points})")

    people = extracted.get("people_count")
    if people is None:
        add("people", 0, "people count unknown (+0)")
    else:
        people_int = max(0, _as_int(people))
        points = min(people_int // PEOPLE_DIVISOR, PEOPLE_CAP)
        add("people", points, f"{people_int} people (+{points})")

    vulns = [str(v) for v in extracted.get("vulnerabilities") or [] if v]
    counted_vulns = vulns[:VULN_TYPE_CAP]
    points = VULN_POINTS_PER_TYPE * len(counted_vulns)
    if counted_vulns:
        add("vulnerability", points, f"vulnerable: {', '.join(counted_vulns)} (+{points})")
    else:
        add("vulnerability", 0, "no noted vulnerabilities (+0)")

    waited = waiting_minutes((incident or {}).get("created_at"), now)
    points = min(waited // WAITING_MINUTES_PER_POINT, WAITING_CAP)
    add("waiting_time", points, f"waited {waited} min (+{points})")

    area_level = str((area or {}).get("level") or "NORMAL").upper()
    if area_level not in AREA_POINTS:
        area_level = "NORMAL"
    points = AREA_POINTS[area_level]
    add("area_pressure", points, f"area pressure {area_level} (+{points})")

    river_risk = str((weather or {}).get("river_risk") or "NORMAL").upper()
    if river_risk not in RIVER_POINTS:
        river_risk = "NORMAL"
    points = RIVER_POINTS[river_risk]
    add("river_risk", points, f"river risk {river_risk} (+{points})")

    # Shelter safety perimeter: an SOS from inside an open shelter with
    # free beds and staff on site is still real, but a boat is rarely the
    # first answer — shelter coordination is. Full shelters give no relief.
    from resqra_agents.tools.geo import nearest_open_shelter

    refuge = nearest_open_shelter((incident or {}).get("location"), shelters)
    if refuge:
        s = refuge["shelter"]
        add("shelter_proximity", -2,
            f"inside {s.get('name')} safety perimeter "
            f"({refuge['distance_m']:.0f}m, {refuge['free']} free beds, staff on site) (-2)")
    else:
        add("shelter_proximity", 0, "not inside an open shelter perimeter (+0)")

    score = max(0, sum(f["points"] for f in factors))
    band = "LOW"
    for band_name, threshold in PRIORITY_BANDS:
        if score >= threshold:
            band = band_name
            break

    return {
        "score": score,
        "band": band,
        "factors": factors,
        "reasons": [f["reason"] for f in factors],
    }
