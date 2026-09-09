"""Phase 5 Strands Intake agent — arch §7.1, §46.

Code-first routing stays in ControlRoomAgent (correctness never depends on
an LLM router). This Strands Agent gives the hackathon-visible tool-calling
surface over the SAME deterministic functions:

- IncidentIntakeAgent: normalize_extraction_tool + regex_extract_tool

Priority scoring is a pure engine (priority_engine.compute_priority) and
needs no agent — see tools/intake_tools.priority_score_tool if a provider
ever wants it behind a model.
"""

from __future__ import annotations

from typing import Any

INTAKE_SYSTEM = (
    "You are the ResQra Incident Intake Agent. Convert resident distress "
    "reports into structured incidents with normalize_extraction_tool and "
    "regex_extract_tool. Never invent coordinates or priority scores. Flag "
    "needs_review when people count or location is missing."
)


def build_intake_agent() -> Any:
    from strands import Agent

    from resqra_agents.tools.intake_tools import (
        normalize_extraction_tool,
        regex_extract_tool,
    )

    return Agent(
        system_prompt=INTAKE_SYSTEM,
        tools=[normalize_extraction_tool, regex_extract_tool],
    )
