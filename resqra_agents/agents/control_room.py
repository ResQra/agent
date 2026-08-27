"""ControlRoomAgent: one-door router, approval gate enforcer, and executor.

Routing is deliberately code-first. An LLM router can be added later, but
correctness must never depend on it. Approvals are pure code too:

    agent recommends (cards) -> human approves -> only code executes.
"""

from __future__ import annotations

import copy

from resqra_agents.agents.monitor import WatchAgent
from resqra_agents.agents.priority import PriorityAgent
from resqra_agents.agents.report_intake import ReportIntakeAgent
from resqra_agents.agents.resident import ResidentAgent
from resqra_agents.agents.team_dispatch import TeamDispatchAgent
from resqra_agents.tools.activity_log import ActivityLog
from resqra_agents.tools.mission_store import MissionStore
from resqra_agents.tools.pending_actions import (
    APPROVED,
    PENDING,
    REJECTED,
    PendingActionsStore,
    RejectionMemory,
)


class ControlRoomAgent:
    """Routes typed tasks to specialist agents and owns the approval gate."""

    def __init__(
        self,
        intake_agent: ReportIntakeAgent | None = None,
        priority_agent: PriorityAgent | None = None,
        dispatch_agent: TeamDispatchAgent | None = None,
        resident_agent: ResidentAgent | None = None,
        watch_agent: WatchAgent | None = None,
        pending_actions: PendingActionsStore | None = None,
        missions: MissionStore | None = None,
        activity_log: ActivityLog | None = None,
        rejection_memory: RejectionMemory | None = None,
    ) -> None:
        self.intake_agent = intake_agent or ReportIntakeAgent()
        self.priority_agent = priority_agent or PriorityAgent()
        self.dispatch_agent = dispatch_agent or TeamDispatchAgent()
        self.resident_agent = resident_agent or ResidentAgent()
        self.pending_actions = pending_actions or PendingActionsStore()
        self.rejection_memory = rejection_memory or RejectionMemory()
        self.missions = missions or MissionStore()
        self.activity = activity_log or ActivityLog()
        self.watch_agent = watch_agent or WatchAgent(
            dispatch_agent=self.dispatch_agent,
            pending_actions=self.pending_actions,
            rejection_memory=self.rejection_memory,
            activity_log=self.activity,
        )

    def dispatch(self, task: dict) -> dict:
        task_type = task.get("type")
        if task_type == "new_distress_msg":
            return self.handle_new_distress_msg(task)
        if task_type == "score_incident":
            return {
                "routed_to": "PriorityAgent",
                "result": self.priority_agent.score(
                    task.get("incident") or {},
                    area=task.get("area"),
                    weather=task.get("weather"),
                    now=task.get("now"),
                ),
            }
        if task_type == "recommend_team":
            return self.handle_recommend_team(task)
        if task_type == "approval_result":
            return self.handle_approval_result(task)
        if task_type == "resident_chat":
            return {
                "routed_to": "ResidentAgent",
                "result": self.resident_agent.chat(
                    str(task.get("user_id") or ""),
                    str(task.get("message") or ""),
                    history=task.get("history") or [],
                ),
            }
        if task_type == "monitor_sweep":
            return {
                "routed_to": "WatchAgent",
                "result": self.watch_agent.sweep(
                    task.get("incidents") or [],
                    task.get("teams") or [],
                    replan=bool(task.get("replan")),
                    now=task.get("now"),
                ),
            }
        if task_type == "list_pending_actions":
            return {
                "routed_to": "ControlRoomAgent",
                "result": {"cards": self.pending_actions.list_pending()},
            }
        raise ValueError(f"unknown control-room task type: {task_type!r}")

    def handle_new_distress_msg(self, task: dict) -> dict:
        raw_text = str(task.get("raw_text") or "").strip()
        if not raw_text:
            raise ValueError("new_distress_msg requires raw_text")

        incident = self.intake_agent.process(raw_text, source=task.get("source", "demo"))
        priority = self.priority_agent.score(
            incident,
            area=task.get("area"),
            weather=task.get("weather"),
            now=task.get("now"),
        )
        incident["priority"] = priority

        recommendation = None
        pending_card = None
        teams = task.get("teams") or []
        if teams:
            recommendation = self.dispatch_agent.recommend(
                incident,
                teams,
                rejected_pairs=self._rejected_pairs(),
            )
            pending_card = self.create_assignment_card(incident, teams, recommendation)

        self.activity.log_event(
            actor="agent",
            type_="distress_processed",
            summary=(
                f"Incident {incident['id']} extracted and scored "
                f"{priority['score']} ({priority['band']})"
            ),
            payload={"incident_id": incident["id"]},
        )
        return {
            "routed_to": "ControlRoomAgent",
            "result": {
                "incident": incident,
                "priority": priority,
                "recommendation": recommendation,
                "pending_action": pending_card,
            },
        }

    def handle_recommend_team(self, task: dict) -> dict:
        incident = task.get("incident") or {}
        teams = task.get("teams") or []
        recommendation = self.dispatch_agent.recommend(
            incident,
            teams,
            rejected_pairs=task.get("rejected_pairs") or self._rejected_pairs(),
        )
        pending_card = self.create_assignment_card(incident, teams, recommendation)
        return {
            "routed_to": "TeamDispatchAgent",
            "result": {
                "recommendation": recommendation,
                "pending_action": pending_card,
            },
        }

    def create_assignment_card(
        self,
        incident: dict,
        teams: list[dict],
        recommendation: dict | None,
    ) -> dict | None:
        """Turn an eligible recommendation into a PENDING card.

        Idempotent per incident+team: no duplicate card while one is still
        pending. Cards carry incident/team snapshots so approval can execute
        without re-asking the caller for state.
        """
        team_id = (recommendation or {}).get("team_id")
        if not team_id:
            return None
        duplicate = any(
            c.get("proposed_team_id") == team_id
            for c in self.pending_actions.list_for_incident(incident.get("id", ""))
            if c.get("state") == PENDING
        )
        if duplicate:
            return None
        team_snapshot = next((t for t in teams or [] if t.get("id") == team_id), {"id": team_id})
        card_payload = {
            "recommendation": {k: v for k, v in recommendation.items() if k != "considered"},
            "incident": copy.deepcopy(incident),
            "team": copy.deepcopy(team_snapshot),
        }
        card = self.pending_actions.create(
            type_="ASSIGN",
            incident_id=str(incident.get("id") or ""),
            proposed_team_id=team_id,
            reasons=recommendation.get("reasons") or [],
            payload=card_payload,
        )
        self.activity.log_event(
            actor="agent",
            type_="allocation_recommended",
            summary=(
                f"Recommend {(recommendation or {}).get('team_name') or team_id} "
                f"for {incident.get('id')} - awaiting coordinator approval"
            ),
            payload={"pending_id": card["id"], "incident_id": incident.get("id")},
        )
        return card

    def handle_approval_result(self, task: dict) -> dict:
        """Gate Enforcer + Action Executor. Pure code, never LLM."""
        pending_id = str(task.get("pending_id") or "")
        decision = str(task.get("decision") or "").upper()
        actor = str(task.get("coordinator_id") or "coordinator")
        note = str(task.get("note") or "")
        override_team_id = task.get("override_team_id")

        card = self.pending_actions.get(pending_id)
        if card is None:
            raise ValueError(f"unknown pending action: {pending_id}")

        if card.get("state") != PENDING:
            # Idempotent double-click / stale console view.
            return {
                "routed_to": "ControlRoomAgent",
                "result": {
                    "pending_action": card,
                    "executed": False,
                    "already_decided": True,
                },
            }

        decided = self.pending_actions.decide(pending_id, decision, actor, note)

        if decision != APPROVED:
            team_id = override_team_id or card.get("proposed_team_id")
            self.rejection_memory.remember(card.get("incident_id"), team_id)
            self.activity.log_event(
                actor="human",
                type_="pending_action_rejected",
                summary=f"Coordinator rejected {pending_id} ({team_id})",
                payload={"pending_id": pending_id, "note": note},
            )
            return {
                "routed_to": "ControlRoomAgent",
                "result": {"pending_action": decided, "executed": False},
            }

        team_id = override_team_id or card.get("proposed_team_id")
        if not team_id:
            raise ValueError("approved action has no team to dispatch")

        payload = card.get("payload") or {}
        incident = copy.deepcopy(payload.get("incident") or {"id": card.get("incident_id")})
        team = copy.deepcopy(payload.get("team") or {"id": team_id})
        if override_team_id:
            team = {"id": team_id}

        mission = self.missions.create_for_assignment(
            card["incident_id"], team_id, pending_action_id=pending_id
        )
        incident.update(status="ASSIGNED", assigned_team=team_id, mission_id=mission["id"])
        team.update(status="ON_MISSION", current_mission_id=mission["id"])

        self.activity.log_event(
            actor="human",
            type_="pending_action_approved",
            summary=(
                f"Approved {pending_id}: {team.get('name') or team_id} dispatched "
                f"on mission {mission['id']}"
            ),
            payload={
                "pending_id": pending_id,
                "incident_id": card["incident_id"],
                "team_id": team_id,
                "mission_id": mission["id"],
            },
        )
        return {
            "routed_to": "ControlRoomAgent",
            "result": {
                "pending_action": decided,
                "mission": mission,
                "incident": incident,
                "team": team,
                "executed": True,
            },
        }

    def _rejected_pairs(self) -> set:
        return self.rejection_memory.pairs()
