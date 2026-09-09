"""Phase 6 Strands supervisor tools — snapshot-based (no DB import).

The deployed agent receives a world snapshot; these tools slice it.
Same allowlist spirit as backend services/ops_tools (read-only).
"""

from __future__ import annotations

from strands import tool


@tool
def get_operational_picture_tool(snapshot: dict) -> dict:
    """Counts + top IDs from a world snapshot."""
    incidents = snapshot.get("open_incidents") or snapshot.get("incidents") or []
    teams = snapshot.get("teams") or []
    critical = [i for i in incidents if (i.get("priority") or {}).get("score", 0) >= 8]
    return {
        "active_incidents": len(incidents),
        "critical": len(critical),
        "teams_available": sum(1 for t in teams if t.get("status") == "AVAILABLE"),
        "teams_total": len(teams),
        "top_ids": {
            "incidents": [i.get("id") for i in incidents[:5]],
            "critical": [i.get("id") for i in critical[:5]],
        },
    }


@tool
def find_available_teams_tool(snapshot: dict, limit: int = 5) -> list:
    """Available teams with capacity from a snapshot."""
    teams = [t for t in (snapshot.get("teams") or [])
             if t.get("status") == "AVAILABLE"]
    return [{"id": t.get("id"), "name": t.get("name"),
             "capacity": t.get("capacity")} for t in teams[:limit]]


@tool
def shelter_space_tool(snapshot: dict, limit: int = 5) -> list:
    """Shelters by free beds from a snapshot."""
    rows = []
    for s in snapshot.get("shelters") or []:
        free = max(0, int(s.get("capacity") or 0) - int(s.get("current_occupancy") or 0))
        rows.append({"id": s.get("id"), "name": s.get("name"), "free": free})
    return sorted(rows, key=lambda r: r["free"], reverse=True)[:limit]
