"""Deterministic team allocation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from resqra_agents.tools.geo import haversine_km

BOAT_SPEED_KMH = 20.0
DISPATCHABLE_STATUSES = {"AVAILABLE", "RETURNING"}

MEDICAL_TOKENS = {"medical", "triage", "health", "red cross", "redcross", "hospital",
                  "doctor", "nurse", "paramedic", "clinic"}
WATER_TOKENS = {"boat", "raft", "marine", "water", "rescue", "amphibious", "assault"}


def _capability_bonus(incident: dict, team: dict) -> tuple[int, str | None]:
    """Soft preference (never disqualifies): medical needs → medical teams."""
    vulns = [str(v).lower() for v in (incident.get("vulnerabilities") or [])]
    needs_medical = any(v in ("pregnant", "ill", "injured", "elderly", "disabled")
                        for v in vulns)
    if not needs_medical:
        return 0, None
    hay = f"{team.get('specialization', '')} {team.get('name', '')}".lower()
    if any(tok in hay for tok in MEDICAL_TOKENS):
        return -1, "medical capability match"
    if any(tok in hay for tok in WATER_TOKENS):
        return 0, None
    return 0, None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    """DB rows occasionally carry "N/A"/None numerics — degrade, don't crash."""
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


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


def recommend_team(incident: dict, teams: list[dict], rejected_pairs: set | None = None,
                   route_check=None, shelters: list | None = None) -> dict:
    """Deterministic allocation. route_check(team, incident) → (feasible, reason)
    optionally gates on Phase 7 routing; comms-offline teams are excluded."""
    from resqra_agents.tools.geo import nearest_open_shelter

    rejected_pairs = rejected_pairs or set()
    need = _people_needed(incident or {})
    refuge = nearest_open_shelter((incident or {}).get("location"), shelters)
    shelter_option = None
    if refuge:
        s = refuge["shelter"]
        shelter_option = {"shelter_id": s.get("id"), "name": s.get("name"),
                          "distance_m": refuge["distance_m"], "free": refuge["free"]}
    considered: list[dict] = []
    eligible: list[tuple[dict, float | None, int]] = []

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

        capacity = _safe_int(team.get("capacity"))
        if capacity < need:
            considered.append({
                "team_id": team_id,
                "team_name": name,
                "ok": False,
                "reason": f"{name} capacity {capacity} < {need} people",
            })
            continue

        if isinstance(team.get("last_problem"), dict) and \
                str(team["last_problem"].get("severity", "")).upper() == "OFFLINE":
            considered.append({
                "team_id": team_id,
                "team_name": name,
                "ok": False,
                "reason": f"{name} reported OFFLINE, not contactable",
            })
            continue

        if route_check is not None:
            try:
                feasible, why = route_check(team, incident or {})
            except Exception:
                feasible, why = True, ""
            if not feasible:
                considered.append({
                    "team_id": team_id,
                    "team_name": name,
                    "ok": False,
                    "reason": f"{name} route infeasible{(': ' + why) if why else ''}",
                })
                continue

        distance = _distance(incident or {}, team)
        bonus, cap_note = _capability_bonus(incident or {}, team)
        eligible.append((team, distance, bonus))
        considered.append({
            "team_id": team_id,
            "team_name": name,
            "ok": True,
            "reason": f"{name} {status.lower()}, capacity {capacity} >= {need} people"
            + (f", {distance:.1f} km away" if distance is not None else "")
            + (f", {cap_note}" if cap_note else ""),
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
            "shelter_option": shelter_option,
        }

    best, distance, _bonus = min(
        eligible,
        key=lambda item: (item[2], item[1] if item[1] is not None else 1e9))
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
    if shelter_option:
        reasons.append(
            f"{shelter_option['name']} {shelter_option['distance_m']:.0f}m away with "
            f"{shelter_option['free']} free beds — coordinate shelter intake before dispatch")

    return {
        "team_id": best.get("id"),
        "team_name": name,
        "distance_km": distance,
        "eta_min": eta,
        "reasons": reasons,
        "considered": considered,
        "shelter_option": shelter_option,
    }
