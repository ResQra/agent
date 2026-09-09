"""Phase 8 Strands resource + comms tools (deterministic, deployable-safe)."""

from __future__ import annotations

from strands import tool


@tool
def recommend_resource_tool(incident: dict, teams: list) -> dict:
    """Constrained allocation: capacity + availability + rejection-aware."""
    from resqra_agents.tools.allocation_engine import recommend_team

    return recommend_team(incident or {}, teams or [])


@tool
def contact_team_tool(team: dict, message: str) -> dict:
    """Simulated contact: OFFLINE/UNAVAILABLE teams time out (§50)."""
    status = str((team or {}).get("status") or "UNKNOWN").upper()
    problem = (team or {}).get("last_problem") if isinstance((team or {}).get("last_problem"), dict) else {}
    if status in ("OFFLINE", "UNAVAILABLE") or str(problem.get("severity", "")).upper() == "OFFLINE":
        return {"delivered": False, "timeout": True, "reply": None,
                "detail": f"{(team or {}).get('name') or (team or {}).get('id')} unreachable"}
    return {"delivered": True, "timeout": False,
            "reply": "Acknowledged — standing by for tasking.", "detail": "delivered"}
