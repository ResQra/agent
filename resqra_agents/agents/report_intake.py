"""ReportIntakeAgent: raw SOS text -> structured incident fields.

Primary path: one Groq LLM call (temperature 0, JSON-only output).
Degraded path: the built-in regex parser runs when no API key is set
or the LLM call fails — an emergency never crashes.

The LLM output is ALWAYS distrusted and run through normalize_extraction()
before use. The regex parser remains the safety net.
"""

from __future__ import annotations

import json
import re
import time
import uuid

from resqra_agents.agents.model import chat_completion, is_configured

# ---------------------------------------------------------------------------
# Whitelists (LLM output is validated against these, never trusted raw)
# ---------------------------------------------------------------------------

URGENCY_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"}
WATER_STATUSES = {"none", "standing", "rising", "fast_rising", "receding", "unknown"}
VULNERABILITY_WHITELIST = {
    "children", "elderly", "disabled", "injured", "pregnant", "medically_dependent",
}

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
    "ek": 1, "do": 2, "dui": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4,
    "paanch": 5, "panch": 5, "paach": 5, "chhah": 6, "chha": 6,
    "saat": 7, "sat": 7, "aath": 8, "ath": 8, "nau": 9, "das": 10,
    "ekta": 1, "duta": 2, "teenta": 3, "charta": 4, "panchta": 5,
}

# Regex fallback keywords (covering English, Nepali, Hindi, Maithili, Bhojpuri)
_VULN_KEYWORDS = {
    "children": ("child", "children", "kid", "kids", "baby", "babies", "bachche", "bacha", "baccha", "bachi", "chhot bacha", "nanhu", "leka"),
    "elderly": ("elderly", "old", "senior", "aged", "buddha", "boodhe", "boodha", "budo", "budi", "aama", "baba", "babuji", "dadi", "dada", "hajurba"),
    "pregnant": ("pregnant", "pregnancy", "garbhawati", "pett se", "pet se", "garbhavati"),
    "disabled": ("disabled", "wheelchair", "apang", "divyang", "apahij"),
    "ill": ("ill", "sick", "fever", "asthma", "dialysis", "bimar", "bimari", "rugna", "dawai"),
    "injured": ("injured", "hurt", "bleeding", "fracture", "ghav", "chot", "ghayel"),
}
_HIGH_WORDS = ("urgent", "fast", "rising", "trapped", "stuck", "help", "bachao", "gohari", "turant", "fasal")
_CRITICAL_WORDS = ("critical", "drowning", "unconscious", "swept", "washed away", "duban", "tatoot", "breach")
_LOW_WORDS = ("safe", "minor", "information", "surakshit")

# Multilingual water status keywords (English, Nepali, Hindi, Maithili, Bhojpuri)
_WATER_RISING_HINDI = (
    "badh raha", "badh gaya", "paani badh", "water badh", "tezi se badh", "pani badh",
    "rise ho raha", "badiraxa", "badh xa", "pani ghus", "paani ghus", "duban",
    "doob gail", "doob raha", "pani bharal", "bandh toot", "tatbandh toot", "ufan",
)
_WATER_FAST_HINDI = ("tezi se", "fast", "rapidly", "turant", "jald", "bheji")
# English water rising patterns
_WATER_RISING_EN = ("water rising", "water is rising", "water entering", "water is entering", "water level rising", "water at our", "water is at our", "ankle deep", "knee deep", "submerged", "overflowed")

# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

_PROMPT_PATH = None


def _load_prompt() -> str:
    global _PROMPT_PATH
    if _PROMPT_PATH is None:
        from pathlib import Path
        _PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "intake.txt"
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# JSON parsing — survives markdown fences, surrounding prose, partial output
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
# Normalization — LLM output is ALWAYS run through this
# ---------------------------------------------------------------------------

def _coerce_people_count(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(1, int(value))
    text = str(value).strip().lower()
    if text in _WORD_NUMBERS:
        return _WORD_NUMBERS[text]
    m = re.search(r"(\d+)", text)
    if m:
        return max(1, int(m.group(1)))
    return None


def normalize_extraction(raw: dict | None) -> dict:
    raw = raw or {}
    people_count = _coerce_people_count(raw.get("people_count"))
    vulnerabilities: list[str] = []
    other_flags: list[str] = []
    raw_vulns = raw.get("vulnerabilities") or []
    if isinstance(raw_vulns, str):
        raw_vulns = [raw_vulns]
    for item in raw_vulns:
        token = str(item).strip().lower().replace(" ", "_").replace("-", "_")
        if token in VULNERABILITY_WHITELIST:
            if token not in vulnerabilities:
                vulnerabilities.append(token)
        elif token and token not in other_flags:
            other_flags.append(token)
    urgency = str(raw.get("urgency") or "").strip().upper()
    if urgency not in URGENCY_LEVELS:
        urgency = "UNKNOWN"
    water_status = str(raw.get("water_status") or "").strip().lower()
    if water_status not in WATER_STATUSES:
        water_status = "unknown"
    location_text = raw.get("location_text")
    location_text = str(location_text).strip() if location_text else None
    if location_text == "":
        location_text = None
    needs_review = bool(raw.get("needs_review")) or (
        people_count is None or location_text is None or urgency == "UNKNOWN"
    )
    return {
        "people_count": people_count,
        "vulnerabilities": vulnerabilities,
        "other_flags": other_flags,
        "urgency": urgency,
        "water_status": water_status,
        "water_rising": water_status in ("rising", "fast_rising"),
        "location_text": location_text,
        "needs_review": needs_review,
    }


# ---------------------------------------------------------------------------
# LLM extraction (primary path)
# ---------------------------------------------------------------------------

def llm_extract(raw_text: str) -> dict | None:
    """One Groq call: distress text -> JSON extraction. Returns None on failure.

    json_mode is deliberately OFF: the prompt instructs the model to output
    JSON-only, and _parse_json_loose handles any surrounding prose or
    markdown fences. This avoids model-specific JSON-mode incompatibilities.
    """
    if not is_configured():
        return None
    text = (raw_text or "").strip()[:2000]
    if not text:
        return None
    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": _load_prompt()},
                {"role": "user", "content": f'Distress message:\n"""\n{text}\n"""'},
            ],
            temperature=0.0,
            max_tokens=800,
        )
        return _parse_json_loose(response)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Regex fallback (degraded mode — works without any API key)
# ---------------------------------------------------------------------------

def regex_extract(raw_text: str) -> dict:
    """Local regex parser. Always succeeds, never crashes."""
    text = (raw_text or "").strip()
    lower = text.lower()
    # people count
    people_count = None
    patterns = [
        r"\b(\d{1,3})\s*(?:people|persons|person|log|members|family|stuck|trapped|jana|aadmi|admi|manus)\b",
        r"\b(?:we are|we're|hum|ham|hami)\s*(\d{1,3})\b",
        r"\b(\d{1,3})\s*(?:adults?|children|kids|elderly)\b",
        r"\b(\d{1,3})\s*(?:of us|of we)\b",
    ]
    counts = []
    for pattern in patterns:
        counts.extend(int(m) for m in re.findall(pattern, lower))
    if counts:
        people_count = max(counts)
    else:
        for word, value in _WORD_NUMBERS.items():
            if re.search(rf"\b{word}\s+(people|persons|members|of us|aadmi|log|jana)\b", lower):
                people_count = value
                break
        # "alone" = 1 person (check before "years old" to avoid 70 years old = 70)
        if people_count is None and re.search(r"\balone\b", lower):
            people_count = 1
        # "X years old" only if no other number found
        if people_count is None:
            m = re.search(r"\b(\d{1,3})\s*years?\s*old\b", lower)
            if m:
                people_count = int(m.group(1))
    # Also check Hindi/Maithili word numbers
    if people_count is None:
        for word, value in _WORD_NUMBERS.items():
            if re.search(rf"\b{word}\b", lower):
                people_count = value
                break
    # vulnerabilities
    vulnerabilities = []
    for label, keywords in _VULN_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            vulnerabilities.append(label)
    # water — check Hindi keywords first, then English
    water_rising = (
        any(w in lower for w in _WATER_RISING_HINDI)
        or any(w in lower for w in _WATER_RISING_EN)
        or ("rising" in lower and "water" in lower)
        or ("entering" in lower and "water" in lower)
        or ("ufan" in lower)
    )
    water_fast = any(w in lower for w in _WATER_FAST_HINDI)
    water_status = "fast_rising" if water_fast and water_rising else (
        "rising" if water_rising else "none"
    )
    # urgency — check English first, then Hindi
    if any(w in lower for w in _CRITICAL_WORDS) or any(w in lower for w in ("turant", "abhi", "jaldi", "gohari")):
        urgency = "CRITICAL"
    elif water_rising or any(w in lower for w in _HIGH_WORDS) or any(w in lower for w in ("phas", "atke", "fase", "fasal", "baadan")):
        urgency = "HIGH"
    elif any(w in lower for w in _LOW_WORDS) or any(w in lower for w in ("surakshit", "safe")):
        urgency = "LOW"
    else:
        urgency = "MEDIUM"
    # location
    location_text = None
    for pat in (r"\bnear\s+([^,.]+)", r"\bat\s+([^,.]+)", r"\bin\s+([^,.]+)",
                r"([\w\s]+)\s+ke paas", r"\bke paas\s+([^,.]+)", r"\bpaas\s+([^,.]+)",
                r"\b(?:gaur|janakpur|birgunj|jaleshwar|saptari|kankarbagh|rajendra nagar|dhanusha|rautahat|malangwa|lahan|balkhu|kupondole)[\w\s]*",
                r"([\w\s]+)\s+(?:hospital|school|temple|bridge|road|chowk|ward)"):
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            location_text = m.group(1 if m.groups() else 0).strip()
            break
    return {
        "people_count": people_count,
        "vulnerabilities": vulnerabilities,
        "other_flags": [],
        "urgency": urgency,
        "water_status": water_status,
        "water_rising": water_status in ("rising", "fast_rising"),
        "location_text": location_text,
        "needs_review": people_count is None or location_text is None,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract(raw_text: str) -> dict:
    """Extract structured fields from distress text.

    Tries the LLM first; falls back to regex on failure or if no API key.
    Output always runs through normalize_extraction().
    """
    llm_result = llm_extract(raw_text)
    if llm_result is not None:
        result = normalize_extraction(llm_result)
        result["_source"] = "llm"
        return result
    result = normalize_extraction(regex_extract(raw_text))
    result["_source"] = "regex"
    return result


class ReportIntakeAgent:
    """Turns raw distress text into a normalized incident draft."""

    def process(self, raw_text: str, source: str = "demo") -> dict:
        text = (raw_text or "").strip()
        extraction = extract(text)
        return {
            "id": f"inc_{uuid.uuid4().hex[:10]}",
            "source": source,
            "status": "NEW",
            "raw_text": text,
            "people": extraction["people_count"],
            "vulnerabilities": extraction["vulnerabilities"],
            "other_flags": extraction["other_flags"],
            "urgency": extraction["urgency"],
            "water_rising": extraction["water_rising"],
            "water_status": extraction["water_status"],
            "location_text": extraction["location_text"],
            "location": self._demo_location(extraction["location_text"]),
            "needs_review": extraction["needs_review"],
            "extraction": extraction,
            "created_at": time.time(),
        }

    def _demo_location(self, location_text: str | None) -> dict | None:
        """Return a location dict from text. In standalone mode there is no
        geocoding backend, so we return the label only. The backend's
        geocoding service will resolve lat/lng when available."""
        if not location_text:
            return None
        return {"label": location_text, "lat": None, "lng": None}

