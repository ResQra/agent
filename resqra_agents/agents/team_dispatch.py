"""TeamDispatchAgent: deterministic team recommendation wrapper."""

from __future__ import annotations

from resqra_agents.tools.allocation_engine import recommend_team


class TeamDispatchAgent:
    """Recommends a team but does not dispatch it."""

    def recommend(
        self,
        incident: dict,
        teams: list[dict],
        rejected_pairs: set | None = None,
    ) -> dict:
        recommendation = recommend_team(incident, teams, rejected_pairs=rejected_pairs)
        return {
            **recommendation,
            "card_text": self.build_card(recommendation, incident),
            "requires_approval": recommendation.get("team_id") is not None,
        }

    def build_card(self, recommendation: dict, incident: dict) -> str:
        if not recommendation.get("team_id"):
            return "No eligible team available. Coordinator review required."
        reasons = "; ".join(recommendation.get("reasons") or [])
        return (
            f"Recommend {recommendation['team_name']} for incident {incident.get('id')}. "
            f"{reasons}. Awaiting coordinator approval."
        )
