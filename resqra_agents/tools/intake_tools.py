"""Phase 5 Strands tools — arch §46-47 (tool-first, deterministic).

LLM extracts facts; these tools normalize + score. The LLM never computes
a priority number (§13-14). All functions are pure/deterministic and safe
to unit-test without keys or DB.
"""

from __future__ import annotations

from typing import Any

from strands import tool


@tool
def normalize_extraction_tool(extraction: dict) -> dict:
    """Validate + normalize raw extraction (whitelists, clamps)."""
    from resqra_agents.agents.report_intake import normalize_extraction

    return normalize_extraction(extraction or {})


@tool
def regex_extract_tool(raw_text: str) -> dict:
    """Deterministic multilingual fallback extractor (no LLM, no network)."""
    from resqra_agents.agents.report_intake import regex_extract

    return regex_extract(raw_text or "")


@tool
def priority_score_tool(incident: dict, area: Any = None, weather: Any = None) -> dict:
    """Deterministic priority math: score + band + factors + reasons."""
    from resqra_agents.tools.priority_engine import compute_priority

    return compute_priority(
        incident or {},
        area=area if isinstance(area, dict) else None,
        weather=weather if isinstance(weather, dict) else None,
    )
