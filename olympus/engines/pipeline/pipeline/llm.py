"""Ollama LLM helper with deterministic local fallback.

All story-text stages try the local Ollama script model first; if Ollama
is offline (or errors), they fall back to a template-based transform so
the Studio pipeline still runs end-to-end with zero cloud dependencies.
"""

from __future__ import annotations

import json
import urllib.request

from pydantic import BaseModel


class LLMResult(BaseModel):
    text: str
    used_llm: bool = False
    model: str = ""


def ollama_generate(
    prompt: str,
    model: str = "",
    timeout: int = 120,
    num_predict: int = 1200,
    temperature: float = 0.3,
) -> LLMResult | None:
    """Try one Ollama /api/generate call. Returns None on any failure."""
    try:
        from stack.config import cfg

        model = model or cfg.ollama.models.script
        url = cfg.ollama.url + "/api/generate"
    except Exception:
        return None
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
    ).encode()
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        text = (data.get("response") or "").strip()
        if not text:
            return None
        return LLMResult(text=text, used_llm=True, model=model)
    except Exception:
        return None
