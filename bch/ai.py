"""Optional AI assistance (Anthropic or OpenAI). The app works fully without it.

AI output is always stored and displayed as an *estimate*, never as a verified fact, and the AI is
only given text that came from the case's real sources.
"""
from __future__ import annotations

import json
import re

import requests

from . import config

TIMEOUT = 60
DEFAULT_MODELS = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4o-mini"}

SYSTEM = (
    "You assess local news reports about police incidents for a YouTube researcher who requests "
    "bodycam footage through public records laws. Use ONLY the text provided. Do not add facts. "
    "If something is not stated, use null. Respond with a single JSON object and nothing else."
)

PROMPT = """Source text (from news articles / police releases):
---
{text}
---
Return JSON with these keys:
  "incident_summary": 1-2 neutral sentences using only facts in the text,
  "incident_date": "YYYY-MM-DD" only if the text states or clearly implies it, else null,
  "incident_date_evidence": the exact words that give the date, or null,
  "agency": responding agency exactly as named in the text, or null,
  "city": city named in the text or null,
  "county": county named in the text or null,
  "interest_score": integer 0-10 for how unusual/compelling this would be as a bodycam video,
  "interest_reason": short reason,
  "footage_likelihood": integer 0-10 that bodycam/dashcam footage of the key moments exists,
  "footage_reason": short reason,
  "sensitive_notes": short note on minors, victims, death, graphic content, or privacy, or null
"""


def provider() -> str:
    p = config.get_env("AI_PROVIDER").strip().lower()
    if p == "anthropic" and config.get_env("ANTHROPIC_API_KEY"):
        return "anthropic"
    if p == "openai" and config.get_env("OPENAI_API_KEY"):
        return "openai"
    return ""


def is_enabled() -> bool:
    return bool(provider())


def _model() -> str:
    return config.get_env("AI_MODEL") or DEFAULT_MODELS.get(provider(), "")


def _complete(prompt: str, max_tokens: int = 700) -> str:
    p = provider()
    if p == "anthropic":
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": config.get_env("ANTHROPIC_API_KEY"),
                     "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": _model(), "max_tokens": max_tokens, "system": SYSTEM,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=TIMEOUT)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    if p == "openai":
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {config.get_env('OPENAI_API_KEY')}"},
            json={"model": _model(), "max_tokens": max_tokens,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]},
            timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("AI is not configured")


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("AI response did not contain JSON")
    return json.loads(m.group(0))


def assess_case(source_text: str) -> dict:
    out = _parse_json(_complete(PROMPT.format(text=source_text[:6000])))
    for k in ("interest_score", "footage_likelihood"):
        try:
            out[k] = max(0, min(10, int(out.get(k) or 0)))
        except (TypeError, ValueError):
            out[k] = None
    out["_model"] = f"{provider()}:{_model()}"
    out["_label"] = "AI-generated estimate - verify against sources"
    return out


def polish_request(draft: str) -> str:
    prompt = ("Improve the clarity and professional tone of this public records request. Keep every fact, "
              "citation, placeholder in [BRACKETS], and list item. Do not add facts. Return JSON "
              '{"text": "..."}.\n\n' + draft)
    return _parse_json(_complete(prompt, max_tokens=2000)).get("text") or draft
