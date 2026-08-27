"""PriorityAgent: deterministic triage wrapper."""

from __future__ import annotations

from resqra_agents.tools.priority_engine import compute_priority


class PriorityAgent:
    """Scores incidents by calling the pure Python priority engine."""

    def score(
        self,
        incident: dict,
        area: dict | None = None,
        weather: dict | None = None,
        now: float | None = None,
    ) -> dict:
        return compute_priority(incident, area=area, weather=weather, now=now)
