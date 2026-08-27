"""LLM model config for the standalone ResQra agent project.

Uses the Groq API directly via the groq SDK (cheapest/fastest for dev).
The model is lazy-loaded so deterministic tools never need a key.
"""

from __future__ import annotations

import os
from functools import lru_cache


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


@lru_cache(maxsize=1)
def _groq_client():
    from groq import Groq

    api_key = _env("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not set. Add it to agents/.env or your shell. "
            "Get a free key at https://console.groq.com/keys"
        )
    return Groq(api_key=api_key)


def chat_completion(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 800,
) -> str:
    """One-shot Groq chat completion. Blocks until response arrives.

    json_mode is intentionally omitted: the prompt instructs the model to
    output JSON-only, and the caller's loose parser handles any surrounding
    prose. This avoids model-specific validation failures on Groq.
    """
    client = _groq_client()
    resp = client.chat.completions.create(
        model=model or _env("GROQ_MODEL", "llama-3.1-8b-instant"),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def is_configured() -> bool:
    """True if Groq API key is set and the SDK is importable."""
    try:
        return bool(_env("GROQ_API_KEY"))
    except Exception:
        return False
