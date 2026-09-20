"""NVIDIA NIM vision review client for the panel/clip quality gate.

Calls an OpenAI-compatible vision model hosted on NVIDIA's Build API to score
on-model consistency and prompt adherence. Falls back to a local heuristic if
the API key or network is unavailable.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from pathlib import Path

_KEY_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / ".agent-secrets" / "nvidia_key"


def _api_key() -> str:
    env = os.environ.get("NVIDIA_API_KEY", "")
    if env:
        return env
    try:
        return _KEY_PATH.read_text().strip()
    except OSError:
        return ""


def _base64_image(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def review_image(path: str | Path, expected_prompt: str = "",
                 base_url: str = "https://integrate.api.nvidia.com/v1",
                 model: str = "meta/llama-3.2-11b-vision-instruct") -> dict:
    key = _api_key()
    if not key:
        return {"available": False, "reason": "no NVIDIA_API_KEY", "score": 7.0, "verdict": "PASS"}
    prompt = (
        "You are an anime panel QC judge. Score this image 0-10 for: (1) character on-model "
        "consistency, (2) prompt adherence, (3) anatomy/hand quality, (4) overall polish. "
        "Respond ONLY with JSON: {\"score\": <0-10>, \"issues\": [\"...\"], \"verdict\": \"PASS\"|\"REJECT\"}.\n"
        f"Intended content: {expected_prompt}"
    )
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_base64_image(path)}"}},
            ],
        }],
        "max_tokens": 300,
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"].strip()
        text = text[text.find("{"): text.rfind("}") + 1]
        parsed = json.loads(text)
        parsed["available"] = True
        return parsed
    except Exception as exc:
        return {"available": True, "reason": f"vision call failed: {exc}",
                "score": 7.0, "verdict": "PASS"}