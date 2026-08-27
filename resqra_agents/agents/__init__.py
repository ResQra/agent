"""Specialist agents used by the standalone ResQra agent project.

Architecture Alignment:
- Supervisor (ControlRoomAgent): Router + Gate Enforcer + Action Executor
- IntakeAgent (ReportIntakeAgent): Groq LLM + Regex Extraction
- ResidentAgent: Conversational LLM + Live Profile Updates (F19)
- MonitorAgent (WatchAgent): Geohash Hotspot Clustering + Replanning Sweeps

Deterministic Tools (Pure Python, No LLM):
- priority_engine: Deterministic F03 priority scoring tool
- allocation_engine: Deterministic team ranking & RejectionMemory tool
"""

from resqra_agents.agents.control_room import ControlRoomAgent
from resqra_agents.agents.monitor import MonitorAgent, WatchAgent
from resqra_agents.agents.priority import PriorityAgent
from resqra_agents.agents.report_intake import ReportIntakeAgent
from resqra_agents.agents.resident import ResidentAgent
from resqra_agents.agents.team_dispatch import TeamDispatchAgent

# Standard aliases matching AGENT_ARCHITECTURES.md
Supervisor = ControlRoomAgent
IntakeAgent = ReportIntakeAgent

__all__ = [
    "Supervisor",
    "ControlRoomAgent",
    "IntakeAgent",
    "ReportIntakeAgent",
    "ResidentAgent",
    "MonitorAgent",
    "WatchAgent",
    "PriorityAgent",
    "TeamDispatchAgent",
]

