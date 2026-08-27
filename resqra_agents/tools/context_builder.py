"""Context builder — assembles incident, team, shelter, and advisory data
into a concise context block for the resident-facing LLM.

This is a pure function with no LLM calls. It shapes data for the prompt.
"""

from __future__ import annotations

import time


def build_resident_context(
    *,
    user_profile: dict | None = None,
    active_incidents: list[dict] | None = None,
    shelters: list[dict] | None = None,
    advisories: list[dict] | None = None,
    max_shelters: int = 3,
    max_advisories: int = 3,
) -> str:
    """Build a context section for the resident LLM prompt.

    Returns a string to inject as a system message before the conversation.
    """
    parts = []

    # Profile
    profile = user_profile or {}
    if profile:
        prof_items = []
        if profile.get("location_text"):
            prof_items.append(f"stated location: {profile['location_text']}")
        if profile.get("people_with"):
            prof_items.append(f"people with them: {profile['people_with']}")
        if profile.get("vulnerabilities"):
            vulns = profile["vulnerabilities"]
            if isinstance(vulns, list):
                prof_items.append(f"vulnerabilities: {', '.join(vulns)}")
        if profile.get("status"):
            prof_items.append(f"status: {profile['status']}")
        if prof_items:
            parts.append("RESIDENT PROFILE: " + "; ".join(prof_items))

    # Active incidents in the area
    incidents = active_incidents or []
    if incidents:
        inc_lines = []
        for inc in incidents[:5]:
            loc = inc.get("location_text") or inc.get("location", {}).get("label") or "unknown"
            ppl = inc.get("people") or "?"
            status = inc.get("status", "NEW")
            inc_lines.append(f"- {inc.get('id', '?')}: {ppl} people near {loc} [{status}]")
        parts.append("ACTIVE INCIDENTS IN AREA:\n" + "\n".join(inc_lines))

    # Shelters
    shelter_list = shelters or []
    if shelter_list:
        s_lines = []
        for s in shelter_list[:max_shelters]:
            cap = s.get("capacity") or "?"
            occ = s.get("current_occupancy") or 0
            free = max(0, int(cap) - int(occ)) if isinstance(cap, (int, float)) else "?"
            loc = s.get("location", {})
            name = s.get("name", "Shelter")
            s_lines.append(f"- {name}: {free} spaces free (capacity {cap}, {occ} occupied)")
        parts.append("NEARBY SHELTERS:\n" + "\n".join(s_lines))

    # Advisories
    adv_list = advisories or []
    if adv_list:
        a_lines = []
        for a in adv_list[:max_advisories]:
            sev = a.get("severity", "INFO")
            title = a.get("title", "")
            body = (a.get("body") or "")[:120]
            a_lines.append(f"- [{sev}] {title}: {body}")
        parts.append("OFFICIAL ADVISORIES:\n" + "\n".join(a_lines))

    if not parts:
        return "No additional context available."
    return "\n\n".join(parts)


def build_rolling_summary(incidents: list[dict]) -> str:
    """One-paragraph situation summary for the resident.

    Focuses on: how many people need help, what areas are affected,
    and what the resident should do.
    """
    total_people = sum(inc.get("people") or 0 for inc in incidents)
    high_priority = [
        inc for inc in incidents
        if (inc.get("priority", {}).get("score", 0) >= 8
            or inc.get("urgency") in ("HIGH", "CRITICAL"))
    ]
    areas = set()
    for inc in incidents:
        loc = inc.get("location_text") or inc.get("location", {}).get("label")
        if loc:
            areas.add(loc)

    lines = []
    if total_people > 0:
        lines.append(f"{total_people} people have requested help")
    if areas:
        lines.append(f"affected areas include: {', '.join(list(areas)[:4])}")
    if high_priority:
        lines.append(f"{len(high_priority)} incidents are high priority")

    if not lines:
        return "Situation is being assessed. Stay safe and keep your phone charged."
    return ". ".join(lines) + ". Help is being coordinated."
