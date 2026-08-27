"""Approval gate: PendingAction state machine + rejection memory.

This is the agent-side mirror of the backend PendingActions table. The rule
it enforces is the most important one in the architecture:

    agent recommends, human approves, only code executes.
"""

from __future__ import annotations

import copy
import time
import uuid

PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
SUPERSEDED = "SUPERSEDED"
DECISIONS = {APPROVED, REJECTED}


class PendingActionsStore:
    """In-memory approval cards. Swap for DynamoDB-backed storage when the
    agent is deployed; the method contract stays the same."""

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    def create(
        self,
        type_: str,
        incident_id: str,
        proposed_team_id: str | None = None,
        reasons: list[str] | None = None,
        payload: dict | None = None,
        supersedes: str | None = None,
    ) -> dict:
        card = {
            "id": f"pa_{uuid.uuid4().hex[:12]}",
            "type": type_,
            "incident_id": incident_id,
            "proposed_team_id": proposed_team_id,
            "reasons": list(reasons or []),
            "state": PENDING,
            "created_at": time.time(),
            "decided_at": None,
            "decided_by": None,
            "decision_note": "",
            "supersedes": supersedes,
            "payload": copy.deepcopy(payload or {}),
        }
        self._items[card["id"]] = card
        return copy.deepcopy(card)

    def get(self, action_id: str) -> dict | None:
        card = self._items.get(action_id)
        return copy.deepcopy(card) if card else None

    def list_pending(self) -> list[dict]:
        cards = [c for c in self._items.values() if c.get("state") == PENDING]
        return copy.deepcopy(sorted(cards, key=lambda c: c["created_at"], reverse=True))

    def list_for_incident(self, incident_id: str) -> list[dict]:
        cards = [c for c in self._items.values() if c.get("incident_id") == incident_id]
        return copy.deepcopy(sorted(cards, key=lambda c: c["created_at"], reverse=True))

    def decide(self, action_id: str, decision: str, actor: str = "", note: str = "") -> dict | None:
        """Transition PENDING -> APPROVED|REJECTED.

        Idempotent on action_id: deciding a card twice returns the already
        decided card unchanged. Unknown ids return None.
        """
        decision = str(decision or "").upper()
        if decision not in DECISIONS:
            raise ValueError("decision must be APPROVED or REJECTED")
        current = self._items.get(action_id)
        if current is None:
            return None
        if current.get("state") != PENDING:
            return copy.deepcopy(current)
        current.update(
            state=decision,
            decided_at=time.time(),
            decided_by=actor,
            decision_note=note,
        )
        return copy.deepcopy(current)


class RejectionMemory:
    """(team_id, incident_id) pairs a coordinator rejected.

    The allocation engine must never recommend the same team for the same
    incident again after a rejection until state changes. Pair order matches
    the architecture contract: (team_id, incident_id).
    """

    def __init__(self) -> None:
        self._pairs: set[tuple[str, str]] = set()

    def remember(self, incident_id: str | None, team_id: str | None) -> None:
        if incident_id and team_id:
            self._pairs.add((str(team_id), str(incident_id)))

    def pairs(self) -> set[tuple[str, str]]:
        return set(self._pairs)
