"""NVIDIA NIM judge client (OpenAI-compatible, hosted).

Used as the *primary* output-quality judge for the panel vision QC
(stage3b) and the clip review (stage_vlm_review), with the local Ollama
models kept on standby as automatic fallback.

Key resolution (in priority order, never committed):
  1. ``NVIDIA_API_KEY`` env var
  2. ``NVIDIA_NIM_API_KEY`` env var
  3. ``[nim] api_key`` in stack.toml

The client is only *available* when ``[nim] enabled`` is true AND a key
resolves. ``judge_vision`` returns ``None`` on any failure (disabled, no key,
transport error, non-2xx, malformed body) so callers transparently fall back
to their existing local-Ollama path -- NIM never hard-fails a stage.
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

import requests

from .config import NimConfig, PipelineConfig, STACK_ROOT

logger = logging.getLogger(__name__)

_ENV_KEYS = ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY")

# Git-ignored local secret file (same pattern as .agent-secrets/hf_token).
_SECRET_FILE = STACK_ROOT / ".agent-secrets" / "nvidia_key"

# Model returns "as a judge" -- keep it deterministic.
_DEFAULT_SYSTEM = "You are a strict, precise anime-video production QC judge."
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_MAX_TOKENS = 2048


def resolve_api_key(cfg: NimConfig) -> str:
    """API key from env vars first, then the git-ignored secret file, then
    stack.toml ``[nim] api_key``."""
    for var in _ENV_KEYS:
        val = os.environ.get(var, "").strip()
        if val:
            return val
    try:
        if _SECRET_FILE.exists():
            val = _SECRET_FILE.read_text(encoding="utf-8").strip()
            if val:
                return val
    except OSError:
        pass
    return (cfg.api_key or "").strip()


def nim_available(cfg: NimConfig) -> bool:
    """True iff NIM judging is enabled AND an API key resolves."""
    return bool(cfg.enabled and resolve_api_key(cfg))


class NIMClient:
    """Minimal OpenAI-compatible vision chat client for NVIDIA NIM."""

    def __init__(
        self,
        config: PipelineConfig | NimConfig,
        *,
        session: requests.Session | None = None,
    ) -> None:
        if isinstance(config, NimConfig):
            self.cfg = config
        else:
            self.cfg = config.nim
        self.session = session or requests.Session()

    def available(self) -> bool:
        return nim_available(self.cfg)

    def _image_data_uri(self, image: Path | bytes) -> str:
        raw = image if isinstance(image, bytes) else Path(image).read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/png;base64,{b64}"

    def judge_vision(
        self,
        prompt: str,
        images: list[Path | bytes],
        *,
        system: str = _DEFAULT_SYSTEM,
        temperature: float = _DEFAULT_TEMPERATURE,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str | None:
        """Send a vision judge request to NIM.

        Returns the model's text content, or ``None`` if NIM is unavailable
        or the call fails (caller falls back to the local Ollama judge).
        """
        if not self.available():
            logger.debug("nim judge unavailable (enabled=%s); using local fallback",
                         self.cfg.enabled)
            return None

        user_content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in images:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": self._image_data_uri(img)},
            })

        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {resolve_api_key(self.cfg)}",
            "Content-Type": "application/json",
        }
        try:
            resp = self.session.post(
                f"{self.cfg.base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.cfg.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except requests.RequestException as exc:
            logger.warning("nim judge request failed; using local fallback: %s", exc)
            return None
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning("nim judge response malformed; using local fallback: %s", exc)
            return None
