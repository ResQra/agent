"""ResidentAgent: safe resident-facing chat shell with Groq LLM.

Primary path: one Groq call with system prompt + history + context.
Degraded path: regex-based extraction + templated reply when no API key.

The agent:
1. Builds context from incident/shelter/advisory data
2. Generates an empathetic reply via LLM
3. Extracts profile updates (location, people, vulnerabilities, status)
4. Returns structured output for the router to persist
"""

from __future__ import annotations

import json
import re
import time

from resqra_agents.agents.model import chat_completion, is_configured
from resqra_agents.tools.context_builder import build_resident_context

# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

_PROMPT_PATH = None


def _load_prompt() -> str:
    global _PROMPT_PATH
    if _PROMPT_PATH is None:
        from pathlib import Path
        _PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "resident.txt"
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Profile extraction prompt (LLM)
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """Extract resident profile updates from this flood-emergency \
chat. Return STRICT JSON only, no markdown:
{"location": <nearest landmark/address string or null>,
 "people_with": <integer of people together or null>,
 "vulnerabilities": <list from: children, elderly, pregnant, disabled, ill, injured; or null>,
 "status": <one of: SAFE, NEEDS_HELP, TRAPPED, EVACUATED; or null>}
Use null for anything not clearly stated in the conversation. Do not guess.

Conversation:
"""


# ---------------------------------------------------------------------------
# JSON parsing (loose)
# ---------------------------------------------------------------------------

def _parse_json_loose(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# Degraded-mode helpers (no LLM)
# ---------------------------------------------------------------------------

def _degraded_reply(text: str, profile: dict) -> str:
    """Rautahat District grounded keyword-based reply when LLM is unavailable."""
    lower = text.lower()
    if any(w in lower for w in ("shelter", "hospital", "camp", "surakshit", "kaha jau", "where to go")):
        return (
            "In Gaur (Rautahat), the open shelters are: (1) Juddha Secondary School Relief Camp (Ward 2), "
            "(2) Rautahat District Sports Stadium Camp, and (3) Gaur District Hospital. "
            "Stay on high ground and avoid moving Bagmati floodwaters."
        )
    if "gaur" in lower or "tikuliya" in lower or "garuda" in lower or "chandrapur" in lower:
        return (
            "I've noted you are in the Gaur/Rautahat flood sector. The GAUR BAGMATI WATER RESCUE UNIT "
            "and APF No. 11 Battalion are operating here. Please stay on your highest floor/rooftop "
            "and tell me: how many people are with you and which Ward or landmark?"
        )
    if any(w in lower for w in ("help", "bachao", "rescue", "save", "trapped", "fas gaye", "fasal chi", "duban")):
        return (
            "I understand you need urgent help. Please stay on the highest floor or rooftop, "
            "away from fast-moving Bagmati/Lalbakaiya floodwaters. Keep your phone dry. "
            "Our coordinator is prioritizing your location."
        )
    if any(w in lower for w in ("safe", "okay", "ok", "theek hai", "safe hoon", "surakshit")):
        return (
            "Good to know you are safe. Stay on high ground and keep your phone charged. "
            "If the water rises, message me immediately."
        )
    if profile.get("location_text") and profile.get("people_with"):
        return (
            f"I have noted your location at {profile['location_text']} with "
            f"{profile['people_with']} people. Gaur rescue teams are on standby. "
            "Stay safe and keep your phone dry."
        )
    return (
        "I am your Rautahat Flood Rescue Assistant. Please tell me your location "
        "in Rautahat (e.g. Gaur Ward 3, Juddha School, Tikuliya) and how many people are with you."
    )


def _degraded_extract(text: str) -> dict:
    """Regex-based extraction when LLM is unavailable."""
    lower = text.lower()
    people = None
    m = re.search(r"(\d{1,3})\s*(?:people|persons|log|members|family|of us|of we|aadmi|jana)", lower)
    if m:
        people = int(m.group(1))
    else:
        for word, val in {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                          "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                          "ek": 1, "do": 2, "dui": 2, "teen": 3, "char": 4, "paanch": 5, "chha": 6, "saat": 7}.items():
            if re.search(rf"\b{word}\b", lower):
                people = val
                break

    location = None
    for pat in (r"\bnear\s+([^,.]+)", r"\bat\s+([^,.]+)", r"\bin\s+([^,.]+)",
                r"\b(?:gaur|tikuliya|garuda|chandrapur|juddha|bagmati|lalbakaiya)[\w\s]*",
                r"([\w\s]+)\s+(?:hospital|school|ward|chowk|ghat)"):
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            location = m.group(1 if m.groups() else 0).strip()
            break

    vulns = []
    for label, kws in {
        "children": ("child", "children", "kid", "kids", "baby"),
        "elderly": ("elderly", "old", "senior"),
        "pregnant": ("pregnant", "pregnancy"),
        "disabled": ("disabled", "wheelchair"),
        "ill": ("ill", "sick", "fever"),
        "injured": ("injured", "hurt", "bleeding"),
    }.items():
        if any(k in lower for k in kws):
            vulns.append(label)

    status = None
    if any(w in lower for w in ("trapped", "stuck", "fas gaye")):
        status = "TRAPPED"
    elif any(w in lower for w in ("safe", "theek")):
        status = "SAFE"
    elif any(w in lower for w in ("help", "rescue", "bachao")):
        status = "NEEDS_HELP"

    return {
        "location": location,
        "people_with": people,
        "vulnerabilities": vulns or None,
        "status": status,
    }


# ---------------------------------------------------------------------------
# LLM chat + extraction
# ---------------------------------------------------------------------------

def _llm_chat(user_id: str, message: str, history: list[dict],
              context_block: str, profile_section: str) -> str | None:
    """One Groq call for the empathetic reply. Returns None on failure."""
    if not is_configured():
        return None
    msgs = [
        {"role": "system", "content": _load_prompt()},
        {"role": "system", "content": context_block},
        {"role": "system", "content": profile_section},
    ]
    for m in history[-20:]:
        role = "assistant" if m.get("role") == "agent" else "user"
        msgs.append({"role": role, "content": str(m.get("content", ""))})
    msgs.append({"role": "user", "content": message})
    try:
        return chat_completion(msgs, temperature=0.3, max_tokens=400)
    except Exception:
        return None


def _llm_extract(user_msg: str, agent_reply: str) -> dict | None:
    """One Groq call for profile extraction. Returns None on failure."""
    if not is_configured():
        return None
    convo = f'user: "{user_msg}"\nassistant: "{agent_reply}"'
    try:
        raw = chat_completion(
            [{"role": "user", "content": _EXTRACTION_PROMPT + convo}],
            temperature=0.0,
            max_tokens=300,
        )
        return _parse_json_loose(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ResidentAgent:
    """Replies calmly and extracts profile updates from resident chat.

    Usage:
        agent = ResidentAgent()
        result = agent.chat(
            user_id="u_abc",
            message="6 people stuck near school, water rising",
            history=[...],
            context={"shelters": [...], "advisories": [...]},
        )
        # result["reply"] — empathetic text
        # result["profile_updates"] — dict for DB persistence
    """

    def chat(
        self,
        user_id: str,
        message: str,
        history: list[dict] | None = None,
        context: dict | None = None,
    ) -> dict:
        text = (message or "").strip()
        history = history or []
        ctx = context or {}

        # Build context block
        context_block = build_resident_context(
            user_profile=ctx.get("user_profile"),
            active_incidents=ctx.get("active_incidents"),
            shelters=ctx.get("shelters"),
            advisories=ctx.get("advisories"),
        )

        # Profile section for memory
        profile = ctx.get("user_profile") or {}
        profile_parts = []
        for k, v in profile.items():
            txt = ", ".join(v) if isinstance(v, list) else str(v)
            profile_parts.append(f"{k.replace('_', ' ')}: {txt}")
        profile_section = (
            "WHAT YOU ALREADY KNOW about this resident (do NOT ask again): "
            + "; ".join(profile_parts) if profile_parts else "WHAT YOU ALREADY KNOW: (nothing yet)"
        )

        # Try LLM path
        reply = _llm_chat(user_id, text, history, context_block, profile_section)
        source = "llm"
        if reply is None:
            reply = _degraded_reply(text, profile)
            source = "degraded"

        # Extract profile updates
        extraction = _llm_extract(text, reply)
        if extraction is None:
            extraction = _degraded_extract(text)
            ext_source = "degraded"
        else:
            ext_source = "llm"

        return {
            "user_id": user_id,
            "reply": reply,
            "profile_updates": {
                "people_with": extraction.get("people_with"),
                "vulnerabilities": extraction.get("vulnerabilities"),
                "location_text": extraction.get("location"),
                "status": extraction.get("status"),
            },
            "source": source,
            "extraction_source": ext_source,
            "degraded": source == "degraded",
            "history_used": len(history),
            "context_block": context_block,
        }
