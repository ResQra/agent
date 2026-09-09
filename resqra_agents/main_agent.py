"""Main Strands agent base for ResQra.

This standalone package is built and deployed separately from the FastAPI
backend. The backend should call the deployed agent later through its
`agents_gateway` seam.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from resqra_agents.agents.control_room import ControlRoomAgent


@dataclass
class AgentRuntimeConfig:
    provider: str
    model: str
    groq_enabled: bool


class ResQraMainAgent:
    """One-door base agent for standalone orchestration."""

    def __init__(self) -> None:
        groq_api_key = os.environ.get("GROQ_API_KEY", "")
        self.runtime = AgentRuntimeConfig(
            provider="groq" if groq_api_key else "local",
            model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
            groq_enabled=bool(groq_api_key),
        )
        self._strands_agent: Any | None = None
        self.control_room = ControlRoomAgent()

    def build_strands_agent(self) -> Any:
        """Create the real Strands Agent lazily.

        Deterministic tools do not require this. Use it when we add LLM
        routing/summarization or deploy to AgentCore.
        """
        if self._strands_agent is not None:
            return self._strands_agent
        try:
            from strands import Agent
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("strands-agents is not installed") from exc

        system_prompt = (
            "You are the main ResQra coordination agent. Route work to "
            "specialist agents, never calculate safety-critical numbers, "
            "and never dispatch teams without human approval."
        )
        self._strands_agent = Agent(system_prompt=system_prompt)
        return self._strands_agent

    def score_incident(
        self,
        incident: dict,
        area: dict | None = None,
        weather: dict | None = None,
        now: float | None = None,
    ) -> dict:
        return self.control_room.dispatch({
            "type": "score_incident",
            "incident": incident,
            "area": area,
            "weather": weather,
            "now": now,
        })["result"]

    def recommend_team(
        self,
        incident: dict,
        teams: list[dict],
        rejected_pairs: set | None = None,
    ) -> dict:
        return self.control_room.dispatch({
            "type": "recommend_team",
            "incident": incident,
            "teams": teams,
            "rejected_pairs": rejected_pairs,
        })["result"]["recommendation"]

    def decide_approval(
        self,
        pending_id: str,
        decision: str,
        coordinator_id: str = "",
        note: str = "",
        override_team_id: str | None = None,
    ) -> dict:
        """Approval gate: APPROVED executes a mission, REJECTED is remembered.

        Idempotent on pending_id — deciding twice never double-executes.
        """
        return self.control_room.dispatch({
            "type": "approval_result",
            "pending_id": pending_id,
            "decision": decision,
            "coordinator_id": coordinator_id,
            "note": note,
            "override_team_id": override_team_id,
        })["result"]

    def list_pending_actions(self) -> list[dict]:
        return self.control_room.dispatch({"type": "list_pending_actions"})["result"]["cards"]

    def dispatch(self, task: dict) -> dict:
        return self.control_room.dispatch(task)


main_agent = ResQraMainAgent()
