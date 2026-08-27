"""Deterministic team allocation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from resqra_agents.tools.geo import haversine_km

BOAT_SPEED_KMH = 20.0
DISPATCHABLE_STATUSES = {"AVAILABLE", "RETURNING"}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _people_needed(incident: dict) -> int:
    extraction = incident.get("extraction") or {}
    value = extraction.get("people_count")
    if value is None:
        value = incident.get("people")
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def _distance(incident: dict, team: dict) -> float | None:
    inc_loc = incident.get("location") or {}
    team_loc = team.get("location") or {}
    ilat = _to_float(inc_loc.get("lat"))
    ilng = _to_float(inc_loc.get("lng"))
    tlat = _to_float(team_loc.get("lat"))
    tlng = _to_float(team_loc.get("lng"))
    if None in (ilat, ilng, tlat, tlng):
        return None
    return round(haversine_km(ilat, ilng, tlat, tlng), 1)


def recommend_team(incident: dict, teams: list[dict], rejected_pairs: set | None = None) -> dict:
    rejected_pairs = rejected_pairs or set()
    need = _people_needed(incident or {})
    considered: list[dict] = []
    eligible: list[tuple[dict, float | None]] = []

    for team in teams or []:
        team_id = team.get("id")
        name = team.get("name") or team_id or "Unknown team"

        if (team_id, (incident or {}).get("id")) in rejected_pairs:
            considered.append({
                "team_id": team_id,
                "team_name": name,
                "ok": False,
                "reason": f"{name} was already rejected for this incident",
            })
            continue

        status = str(team.get("status") or "UNKNOWN").upper()
        if status not in DISPATCHABLE_STATUSES:
            considered.append({
                "team_id": team_id,
                "team_name": name,
                "ok": False,
                "reason": f"{name} is {status}, not dispatchable",
            })
            continue

        capacity = int(team.get("capacity") or 0)
        if capacity < need:
            considered.append({
                "team_id": team_id,
                "team_name": name,
                "ok": False,
                "reason": f"{name} capacity {capacity} < {need} people",
            })
            continue

        distance = _distance(incident or {}, team)
        eligible.append((team, distance))
        considered.append({
            "team_id": team_id,
            "team_name": name,
            "ok": True,
            "reason": f"{name} {status.lower()}, capacity {capacity} >= {need} people"
            + (f", {distance:.1f} km away" if distance is not None else ""),
        })

    if not eligible:
        failed = "; ".join(c["reason"] for c in considered if not c["ok"])
        return {
            "team_id": None,
            "team_name": None,
            "distance_km": None,
            "eta_min": None,
            "reasons": ["No eligible team" + (f": {failed}" if failed else "")],
            "considered": considered,
        }

    best, distance = min(eligible, key=lambda pair: pair[1] if pair[1] is not None else 1e9)
    name = best.get("name") or best.get("id") or "Unknown team"
    capacity = int(best.get("capacity") or 0)
    reasons = [
        f"{name} is {str(best.get('status') or '').lower()} now",
        f"capacity {capacity} >= {need} people",
    ]
    eta = None
    if distance is not None:
        eta = round(distance / BOAT_SPEED_KMH * 60)
        reasons.append(f"nearest eligible team: {distance:.1f} km away, ETA about {eta} min")
    else:
        reasons.append("incident location unverified, choosing by availability and capacity")

    for item in considered:
        if not item["ok"]:
            reasons.append(item["reason"])

    return {
        "team_id": best.get("id"),
        "team_name": name,
        "distance_km": distance,
        "eta_min": eta,
        "reasons": reasons,
        "considered": considered,
    }
