"""NVIDIA NIM vision review client for the panel/clip quality gate.

Calls an explicitly enabled OpenAI-compatible vision model. Unavailable or
failed judges never pass an artifact.
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


def _local_ollama_review(path: str | Path, expected_prompt: str) -> dict:
    """Use the configured local Ollama VLM before considering hosted review."""
    try:
        from stack.config import cfg

        model = cfg.ollama.models.review
        url = cfg.ollama.url + "/api/chat"
    except Exception as exc:
        return {"available": False, "reason": f"local config unavailable: {exc}"}
    prompt = (
        "You are an anime panel QC judge. Score 0-10 for character consistency, "
        "prompt adherence, anatomy, and overall polish. Respond ONLY as JSON with "
        "score, issues, verdict (PASS or REJECT). Intended content: " + expected_prompt
    )
    payload = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": prompt,
                      "images": [_base64_image(path)]}],
        "options": {"temperature": 0},
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        text = data.get("message", {}).get("content", "").strip()
        text = text[text.find("{"): text.rfind("}") + 1]
        parsed = json.loads(text)
        parsed["available"] = True
        parsed["provider"] = "ollama"
        return parsed
    except Exception as exc:
        return {"available": False, "reason": f"local vision call failed: {exc}"}


def review_image(path: str | Path, expected_prompt: str = "",
                 base_url: str = "https://integrate.api.nvidia.com/v1",
                 model: str = "meta/llama-3.2-11b-vision-instruct") -> dict:
    local = _local_ollama_review(path, expected_prompt)
    if local.get("available"):
        return local
    key = _api_key()
    if not key:
        return {"available": False, "reason": "no NVIDIA_API_KEY", "score": 0.0, "verdict": "UNAVAILABLE"}
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
        return {"available": False, "reason": f"vision call failed: {exc}",
                "score": 0.0, "verdict": "UNAVAILABLE"}
