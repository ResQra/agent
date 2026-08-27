"""Append-only activity log for the agent timeline (F09 behavior)."""

from __future__ import annotations

import copy
import time
import uuid


class ActivityLog:
    def __init__(self) -> None:
        self._events: list[dict] = []

    def log_event(
        self,
        actor: str,
        type_: str,
        summary: str,
        payload: dict | None = None,
    ) -> dict:
        event = {
            "id": f"act_{uuid.uuid4().hex[:12]}",
            "actor": actor,
            "type": type_,
            "summary": summary,
            "payload": payload or {},
            "ts": time.time(),
        }
        self._events.append(event)
        return copy.deepcopy(event)

    def recent(self, limit: int = 50) -> list[dict]:
        return copy.deepcopy(list(reversed(self._events[-limit:])))
