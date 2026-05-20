"""Groq client wiring and prompt helpers.

This is the LLM-facing layer of the RAG pipeline.  The client itself is
constructed lazily so that importing the package does not crash when
``GROQ_API_KEY`` is missing - the legacy app raised at import time which
made unit tests difficult.  ``smartkcet.main`` still calls
:func:`get_groq_client` on startup so the failure mode is preserved for the
runtime entry point.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Iterable, List, Optional, Set

from groq import Groq

from ..config import require_groq_api_key

logger = logging.getLogger("smartkcet.rag.groq_client")

_client: Optional[Groq] = None


class GroqAPIKeyError(ValueError):
    """Raised when the Groq API key is missing, placeholder, or invalid."""
    pass


def _mask_key(key: str) -> str:
    """Return a masked version of the API key for logging (e.g., gsk_xxx***)."""
    if not key:
        return "(empty)"
    if len(key) <= 8:
        return key[:3] + "***"
    return key[:7] + "***" + key[-3:]


def validate_groq_api_key() -> str:
    """Validate the Groq API key at startup. Returns the key or raises GroqAPIKeyError."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()

    if not api_key:
        raise GroqAPIKeyError(
            "GROQ_API_KEY is not set in the environment. "
            "Add it to backend/.env file."
        )

    # Detect common placeholder values
    placeholders = {
        "your-groq-api-key-here",
        "your_groq_api_key",
        "sk-xxx",
        "gsk_xxx",
        "CHANGE_ME",
        "placeholder",
        "your-api-key",
    }
    if api_key.lower() in placeholders or api_key.startswith("your-"):
        raise GroqAPIKeyError(
            f"GROQ_API_KEY appears to be a placeholder value ({_mask_key(api_key)}). "
            "Get a real API key from https://console.groq.com/keys"
        )

    # Groq keys typically start with "gsk_"
    if not api_key.startswith("gsk_"):
        logger.warning(
            "GROQ_API_KEY does not start with 'gsk_' (got: %s). "
            "This may be invalid. Groq API keys typically start with 'gsk_'.",
            _mask_key(api_key),
        )

    logger.info("GROQ_API_KEY detected: %s", _mask_key(api_key))
    return api_key


def get_groq_client() -> Groq:
    """Return a process-wide Groq client, creating it on first use."""

    global _client
    if _client is None:
        api_key = validate_groq_api_key()
        _client = Groq(api_key=api_key)
        logger.info("Groq client initialized successfully (model: llama-3.3-70b-versatile)")
    return _client


def reset_groq_client() -> None:
    """Force re-creation of the Groq client on next use. Call after .env changes."""
    global _client
    _client = None


def parse_llm_json(raw: str) -> List[dict]:
    """Robustly extract a JSON array of question dicts from an LLM response."""

    original = raw
    raw = raw.strip()
    raw = re.sub(r"^```(?:json|)\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\n?```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "questions" in data:
            return data["questions"]
    except json.JSONDecodeError as exc:
        print(f"Direct JSON parse failed: {exc}")
    try:
        match = re.search(r"\[\s*\{.*?\}\s*\]", original, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if isinstance(data, list):
                return data
    except Exception:
        pass
    print("Failed to parse JSON completely.")
    return []


def generate_mcq_set(
    context_chunks: Iterable[str],
    subject: str,
    set_label: str,
    used_questions: Set[str],
) -> List[dict]:
    """Generate a 20-question MCQ set for ``subject`` using ``context_chunks``."""

    chunks = list(context_chunks)
    context = "\n\n".join(chunks[:8])
    used_str = (
        "\n".join(f"- {q}" for q in list(used_questions)[:20])
        if used_questions
        else "None"
    )

    prompt = f"""You are creating a 20-question MCQ exam paper (Set {set_label}) for: {subject}.

Below is the actual content from uploaded question papers. Use ONLY these topics:
---
{context}
---

Questions already used in other sets (DO NOT repeat these):
{used_str}

RULES:
- Generate EXACTLY 20 MCQ questions
- Each question must have exactly 4 options
- Base questions ONLY on topics from the source content above
- Do NOT repeat any question from the used list
- ans must be the integer index of the correct option (0, 1, 2, or 3)
- Each question is worth 1 mark

Output ONLY a valid JSON array of exactly 20 items. Each item:
{{"q":"question text","type":"MCQ","topic":"topic name","opts":["option A","option B","option C","option D"],"ans":0,"marks":1}}"""

    try:
        client = get_groq_client()
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=4096,
        )
        questions = parse_llm_json(resp.choices[0].message.content)
    except GroqAPIKeyError:
        # Re-raise key errors so the generate endpoint can surface them clearly
        raise
    except Exception as exc:
        exc_str = str(exc).lower()
        # Detect authentication errors and re-raise with a clear message
        if "invalid_api_key" in exc_str or "authentication" in exc_str or "401" in exc_str:
            raise GroqAPIKeyError(
                f"Groq API key is invalid or expired. Error: {exc}. "
                "Get a new key from https://console.groq.com/keys and update backend/.env"
            ) from exc
        logger.error("Error calling Groq API: %s", exc)
        raise RuntimeError(f"Groq API call failed: {exc}") from exc

    valid_questions: List[dict] = []
    for q in questions:
        if not isinstance(q, dict) or "q" not in q or "opts" not in q or "ans" not in q:
            continue
        q["id"] = f"{set_label}-{len(valid_questions)}"
        q["type"] = q.get("type", "MCQ")
        q["marks"] = q.get("marks", 1)
        used_questions.add(q.get("q", ""))
        valid_questions.append(q)
    return valid_questions[:20]


def detect_subject(sample_text: str) -> Optional[str]:
    """Ask Groq to label a small text sample with a subject name.

    Returns ``None`` on any failure so callers can fall back to a default.
    """

    try:
        client = get_groq_client()
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "What subject is this exam paper about? Reply with just the "
                        f"subject name, nothing else.\n{sample_text[:500]}"
                    ),
                }
            ],
            temperature=0.1,
            max_tokens=20,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None
