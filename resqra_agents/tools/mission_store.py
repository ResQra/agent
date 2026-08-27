"""Mission store: created only after a coordinator approves a card."""

from __future__ import annotations

import copy
import time
import uuid


class MissionStore:
    """In-memory missions. Mirrors the backend Missions table contract."""

    def __init__(self) -> None:
        self._missions: dict[str, dict] = {}

    def create_for_assignment(
        self,
        incident_id: str,
        team_id: str,
        pending_action_id: str | None = None,
    ) -> dict:
        mission = {
            "id": f"mis_{uuid.uuid4().hex[:12]}",
            "incident_id": incident_id,
            "team_id": team_id,
            "status": "ACTIVE",
            "started_at": time.time(),
            "pending_action_id": pending_action_id,
        }
        self._missions[mission["id"]] = mission
        return copy.deepcopy(mission)

    def get(self, mission_id: str) -> dict | None:
        mission = self._missions.get(mission_id)
        return copy.deepcopy(mission) if mission else None

    def list(self) -> list[dict]:
        return copy.deepcopy(list(self._missions.values()))
