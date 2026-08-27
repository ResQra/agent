"""WatchAgent: scheduled sweep for hotspots, escalations, and replanning.

95% deterministic. The autonomy is in the loop, not in intelligence:
clustering, timers and threshold checks are plain reviewable Python.
When ``replan`` is enabled it turns findings into PendingAction cards so
the "agent recommends, human approves" rule also covers monitoring.
"""

from __future__ import annotations

import copy
import time

from resqra_agents.tools.geo import geohash_encode

OPEN_STATUSES = {"NEW", "VERIFIED", "PRIORITIZED", "ASSIGNED", "IN_PROGRESS"}
HOTSPOT_MIN_REQUESTS = 4
HOTSPOT_MIN_PEOPLE = 12
RISING_MIN_REQUESTS = 2
DELAY_THRESHOLD_MIN = 20
GEOHASH_PRECISION = 6


class WatchAgent:
    """Finds hotspots, delayed incidents, shortages, team disruptions —
    and creates approval cards for unassigned high-priority incidents."""

    def __init__(
        self,
        dispatch_agent=None,
        pending_actions=None,
        rejection_memory=None,
        activity_log=None,
    ) -> None:
        # Optional collaborators; sweep still works without them (findings only).
        self.dispatch_agent = dispatch_agent
        self.pending_actions = pending_actions
        self.rejection_memory = rejection_memory
        self.activity_log = activity_log

    def sweep(
        self,
        incidents: list[dict],
        teams: list[dict],
        replan: bool = False,
        now: float | None = None,
    ) -> dict:
        current = now if now is not None else time.time()
        open_incidents = [i for i in incidents or [] if i.get("status") in OPEN_STATUSES]

        available_capacity = sum(
            int(t.get("capacity") or 0)
            for t in teams or []
            if str(t.get("status") or "").upper() == "AVAILABLE"
        )
        demand_people = sum(int(i.get("people") or 1) for i in open_incidents)

        hotspots = self.find_hotspots(open_incidents)
        delayed = [
            {
                "incident_id": i.get("id"),
                "unresolved_min": int((current - float(i.get("created_at") or current)) // 60),
                "action": "bump+notify",
            }
            for i in open_incidents
            if current - float(i.get("created_at") or current) >= DELAY_THRESHOLD_MIN * 60
        ]
        unassigned_needing_team = [
            i.get("id")
            for i in open_incidents
            if not i.get("assigned_team")
            and (i.get("priority") or {}).get("band") in {"HIGH", "CRITICAL"}
        ]
        team_disruptions = [
            {"team_id": t.get("id"), "affected_mission": t.get("current_mission_id")}
            for t in teams or []
            if str(t.get("status") or "").upper() in {"OFFLINE", "UNAVAILABLE"}
            and t.get("current_mission_id")
        ]

        findings = {
            "open_incidents": len(open_incidents),
            "demand_people": demand_people,
            "available_capacity": available_capacity,
            "shortage": demand_people > available_capacity,
            "hotspots": hotspots,
            "escalations": delayed,
            "delayed_incidents": [d["incident_id"] for d in delayed],
            "unassigned_high_priority": unassigned_needing_team,
            "team_disruptions": team_disruptions,
        }

        if replan:
            findings["pending_actions_created"] = self.recommend_for_unassigned(
                open_incidents, teams or [], unassigned_needing_team
            )
        else:
            findings["pending_actions_created"] = []

        findings["summary"] = self.summarize(findings)
        return findings

    def find_hotspots(self, open_incidents: list[dict]) -> list[dict]:
        buckets: dict[str, dict] = {}
        for incident in open_incidents:
            loc = incident.get("location") or {}
            lat, lng = loc.get("lat"), loc.get("lng")
            if lat is None or lng is None:
                continue
            gh = geohash_encode(float(lat), float(lng), GEOHASH_PRECISION)
            bucket = buckets.setdefault(
                gh,
                {
                    "geohash": gh,
                    "request_count": 0,
                    "people_count": 0,
                    "high_urgency_count": 0,
                    "level": "NORMAL",
                },
            )
            bucket["request_count"] += 1
            bucket["people_count"] += int(incident.get("people") or 1)
            priority = incident.get("priority") or {}
            if priority.get("score", 0) >= 8 or str(incident.get("urgency") or "").upper() == "HIGH":
                bucket["high_urgency_count"] += 1

        hotspots = []
        for bucket in buckets.values():
            if (
                bucket["request_count"] >= HOTSPOT_MIN_REQUESTS
                or bucket["people_count"] >= HOTSPOT_MIN_PEOPLE
            ):
                bucket["level"] = "HOTSPOT"
            elif bucket["request_count"] >= RISING_MIN_REQUESTS:
                bucket["level"] = "RISING"
            if bucket["level"] in {"HOTSPOT", "RISING"}:
                hotspots.append(bucket)
        return sorted(hotspots, key=lambda h: h["high_urgency_count"], reverse=True)

    def recommend_for_unassigned(
        self,
        open_incidents: list[dict],
        teams: list[dict],
        unassigned_ids: list[str],
    ) -> list[dict]:
        """Create one PENDING card per unassigned high-priority incident.

        Skips duplicates: an identical PENDING proposal for the same
        incident+team is never created twice. Rejection memory is honored.
        """
        if not (self.dispatch_agent and self.pending_actions):
            return []

        rejected = self.rejection_memory.pairs() if self.rejection_memory else set()
        existing_pending = self.pending_actions.list_pending()
        by_id = {i.get("id"): i for i in open_incidents}

        created: list[dict] = []
        for incident_id in unassigned_ids:
            incident = by_id.get(incident_id)
            if incident is None:
                continue
            recommendation = self.dispatch_agent.recommend(
                incident, teams, rejected_pairs=rejected
            )
            team_id = recommendation.get("team_id")
            if not team_id:
                continue
            duplicate = any(
                c.get("incident_id") == incident_id and c.get("proposed_team_id") == team_id
                for c in existing_pending
            )
            if duplicate:
                continue
            team_snapshot = next((t for t in teams if t.get("id") == team_id), {"id": team_id})
            card = self.pending_actions.create(
                type_="ASSIGN",
                incident_id=incident_id,
                proposed_team_id=team_id,
                reasons=recommendation.get("reasons") or [],
                payload={
                    "recommendation": recommendation,
                    "incident": copy.deepcopy(incident),
                    "team": copy.deepcopy(team_snapshot),
                },
            )
            created.append(card)
            if self.activity_log is not None:
                self.activity_log.log_event(
                    actor="agent",
                    type_="watch_replan_recommended",
                    summary=(
                        f"WatchAgent proposes {recommendation.get('team_name') or team_id} "
                        f"for {incident_id} after sweep"
                    ),
                    payload={"pending_id": card["id"], "incident_id": incident_id},
                )
        return created

    def summarize(self, findings: dict) -> str:
        parts: list[str] = []
        if findings["shortage"]:
            parts.append(
                f"capacity shortage: {findings['demand_people']} people need help, "
                f"{findings['available_capacity']} seats available"
            )
        for hotspot in findings["hotspots"]:
            parts.append(
                f"{hotspot['geohash']}: {hotspot['request_count']} request(s), "
                f"{hotspot['high_urgency_count']} high urgency - {hotspot['level']}"
            )
        if findings["delayed_incidents"]:
            parts.append(f"{len(findings['delayed_incidents'])} incident(s) waiting over {DELAY_THRESHOLD_MIN} minutes")
        if findings["unassigned_high_priority"]:
            parts.append(
                f"{len(findings['unassigned_high_priority'])} high-priority incident(s) still need team assignment"
            )
        if findings["team_disruptions"]:
            parts.append(f"{len(findings['team_disruptions'])} team disruption(s) need replanning")
        return "; ".join(parts) if parts else "No significant changes."


# Backwards-compatible alias: the architecture doc calls this agent WatchAgent;
# earlier code knew it as MonitorAgent.
MonitorAgent = WatchAgent
