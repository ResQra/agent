"""Phase 6 Strands Supervisor Agent — arch §8 (visible tool surface).

Backend gateway/supervisor.py owns production reasoning over live repos;
this Agent mirrors it with snapshot tools for demos/evals. Broad read-only
visibility, no execution: recommendations always need human approval.
"""

from __future__ import annotations

from typing import Any

SUPERVISOR_SYSTEM = (
    "You are the ResQra Coordinator Supervisor Agent. Understand the whole "
    "operational picture with get_operational_picture_tool, "
    "find_available_teams_tool and shelter_space_tool. Cite exact IDs. "
    "Recommend actions; never claim to have executed anything. Ask for "
    "human approval on consequential steps and explain uncertainty."
)


def build_supervisor_agent() -> Any:
    from strands import Agent

    from resqra_agents.tools.supervisor_tools import (
        find_available_teams_tool,
        get_operational_picture_tool,
        shelter_space_tool,
    )

    return Agent(
        system_prompt=SUPERVISOR_SYSTEM,
        tools=[get_operational_picture_tool, find_available_teams_tool,
               shelter_space_tool],
    )
