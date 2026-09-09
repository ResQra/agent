"""Phase 7 Strands route tools — candidate interpretation (no geometry math)."""

from __future__ import annotations

from strands import tool


@tool
def explain_routes_tool(routes: list) -> dict:
    """Pick cheapest feasible candidate and explain rejections."""
    feasible = [r for r in (routes or []) if isinstance(r, dict) and r.get("feasible")]
    invalid = [r for r in (routes or []) if isinstance(r, dict) and not r.get("feasible")]
    if not routes:
        return {"recommended_id": None, "explanation": "No route candidates available.",
                "invalid": []}
    if not feasible:
        return {"recommended_id": None,
                "explanation": "No feasible route. Request alternate analysis or escalate.",
                "invalid": [{"id": r.get("id")} for r in invalid]}
    best = min(feasible, key=lambda r: (r.get("distance_km") or 1e9))
    return {"recommended_id": best.get("id"),
            "explanation": f"{best.get('id')} ({best.get('distance_km')} km) is currently "
                           "the best feasible option.",
            "invalid": [{"id": r.get("id"), "reason": r.get("blocked_reason")} for r in invalid]}
