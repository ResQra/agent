"""Agent HTTP wrapper — exposes the standalone ResQra agents as a
FastAPI service with a single POST /tasks endpoint.

The backend calls this via httpx when settings.resqra_agent_url is set.
In local dev, the backend imports agents directly (gateway.py seam).

Supports two envelope styles:
  1. ControlRoomAgent style: {"type": "score_incident", "incident": {...}}
  2. HTTP convenience style: {"task_type": "triage", "payload": {...}}

Both are routed through the ControlRoomAgent for consistency.

Usage:
    uvicorn app.http_server:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="ResQra Agent Service", version="0.1.0")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    """Accepts either ControlRoom envelope or convenience format.

    ControlRoom envelope (preferred — matches backend gateway):
        {"type": "score_incident", "incident": {...}}

    Convenience format:
        {"task_type": "triage", "payload": {...}}
    """
    # ControlRoom envelope fields (preferred)
    type: str | None = None

    # Convenience envelope fields
    task_type: str | None = None
    payload: dict | None = None

    class Config:
        extra = "allow"  # pass-through for incident, teams, raw_text, etc.


class TaskResponse(BaseModel):
    result: dict
    elapsed_ms: int


# ---------------------------------------------------------------------------
# Envelope normalization — both styles → ControlRoom task dict
# ---------------------------------------------------------------------------

# Maps convenience task_type names → ControlRoom type names
_TYPE_MAP = {
    "intake": "new_distress_msg",
    "triage": "score_incident",
    "recommend": "recommend_team",
    "resident_chat": "resident_chat",
    "weather": "weather",
    "context": "context",
}


def _normalize_envelope(body: TaskRequest) -> dict:
    """Convert any accepted envelope into a ControlRoom-compatible task dict."""

    # Style 1: ControlRoom envelope — {"type": "score_incident", ...}
    if body.type is not None:
        # Everything except 'type' is already in the right shape.
        extras = {k: v for k, v in body.__dict__.items()
                  if k not in ("type", "task_type", "payload") and v is not None}
        if body.payload:
            extras.update(body.payload)
        return {"type": body.type, **extras}

    # Style 2: Convenience envelope — {"task_type": "triage", "payload": {...}}
    if body.task_type is not None:
        mapped_type = _TYPE_MAP.get(body.task_type, body.task_type)
        inner = dict(body.payload or {})

        # Reshape convenience payloads into ControlRoom contract where needed
        if body.task_type == "triage":
            # Convenience: {"people": 5, "urgency": "HIGH", ...}
            # ControlRoom expects: {"incident": {...}}
            if "incident" not in inner:
                inner = {"incident": inner}
        elif body.task_type == "intake":
            # Convenience: {"raw_text": "..."} → keep as-is; ControlRoom expects raw_text
            pass

        return {"type": mapped_type, **inner}

    raise ValueError("Request must include 'type' (ControlRoom envelope) or 'task_type' (convenience)")


# ---------------------------------------------------------------------------
# Agent singleton (lazy init)
# ---------------------------------------------------------------------------

_main_agent = None


def _get_main_agent():
    global _main_agent
    if _main_agent is None:
        from resqra_agents import main_agent
        _main_agent = main_agent
    return _main_agent


# ---------------------------------------------------------------------------
# Standalone tool handlers (not in ControlRoom)
# ---------------------------------------------------------------------------

def _handle_weather(payload: dict) -> dict:
    from resqra_agents.tools.weather import get_weather
    return get_weather(
        lat=payload.get("lat", 0),
        lng=payload.get("lng", 0),
    )


def _handle_context(payload: dict) -> dict:
    from resqra_agents.tools.context_builder import build_resident_context
    return {"context": build_resident_context(
        user_profile=payload.get("user_profile"),
        active_incidents=payload.get("active_incidents"),
        shelters=payload.get("shelters"),
        advisories=payload.get("advisories"),
    )}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def _dispatch(task: dict) -> dict:
    task_type = task.get("type")

    # Standalone tool endpoints (not routed through ControlRoom)
    if task_type == "weather":
        return _handle_weather(task)
    if task_type == "context":
        return _handle_context(task)

    # Everything else goes through ControlRoom for consistency
    agent = _get_main_agent()
    return agent.dispatch(task)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/tasks", response_model=TaskResponse)
def handle_task(body: TaskRequest):
    start = time.time()
    try:
        task = _normalize_envelope(body)
        result = _dispatch(task)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")
    elapsed = int((time.time() - start) * 1000)
    return TaskResponse(result=result, elapsed_ms=elapsed)


@app.get("/health")
def health():
    return {"status": "ok", "service": "resqra-agents"}
