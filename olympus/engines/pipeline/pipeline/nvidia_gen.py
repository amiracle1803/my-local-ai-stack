"""NVIDIA Build (hosted, free-tier) generation backend.

Python guide for the Studio "NVIDIA" engine option. It offloads the heavy
generation work -- LLM story text, vision QC, and (best-effort) images -- from
the local 8GB card to NVIDIA's OpenAI-compatible hosted API, freeing VRAM for
ComfyUI. It never hard-fails a stage: every method returns ``None``/``False``
on any error so callers transparently fall back to the local Ollama/ComfyUI
path.

Endpoints (verified live 2026-09-05):
  * chat       POST {base}/chat/completions   -- deepseek-v4-flash etc.
  * vision QC  POST {base}/chat/completions   -- llama-3.2-{11b,90b}-vision-instruct
  * image      POST {base}/chat/completions   -- google/diffusiongemma (plans a
    ``dalle.text2im`` action; executing the plan needs the separate
    ``ai.api.nvidia.com/v1/genai`` host, so image gen here is best-effort and
    returns False if the image cannot be realised, falling back to local).

API key resolution (never committed): NVIDIA_API_KEY / NVIDIA_NIM_API_KEY env
var, then .agent-secrets/nvidia_key, then [nim] api_key in stack.toml.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

_ENV_KEYS = ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY")

# default / verified model roles on the free NVIDIA Build tier
DEFAULT_TEXT_MODEL = "deepseek-ai/deepseek-v4-flash-0731"
DEFAULT_VISION_MODEL = "meta/llama-3.2-11b-vision-instruct"
DEFAULT_IMAGE_MODEL = "google/diffusiongemma-26b-a4b-it"

_SUPPORTED_IMAGE_MODELS = {"google/diffusiongemma-26b-a4b-it"}

# Circuit breaker: the free NVIDIA tier rate-limits hard (2 quick 200s then a
# 529 / long read-timeouts). After _FAIL_THRESHOLD consecutive failures the
# client trips open for _COOLDOWN_S, so heavy multi-call stages fall back to
# local Ollama immediately instead of hanging on a 120s timeout every call.
_FAIL_THRESHOLD = 3
_COOLDOWN_S = 60
_circuit = {"failures": 0, "open_until": 0.0}


def _circuit_open() -> bool:
    return time.time() < _circuit["open_until"]


def _circuit_record(failed: bool) -> None:
    if failed:
        _circuit["failures"] += 1
        if _circuit["failures"] >= _FAIL_THRESHOLD:
            _circuit["open_until"] = time.time() + _COOLDOWN_S
            logger.warning(
                "nvidia circuit breaker tripped (%d consecutive failures); "
                "using local fallback for %ss", _circuit["failures"], _COOLDOWN_S,
            )
    else:
        _circuit["failures"] = 0
        _circuit["open_until"] = 0.0


def resolve_api_key(cfg: Any) -> str:
    for var in _ENV_KEYS:
        val = os.environ.get(var, "").strip()
        if val:
            return val
    # git-ignored local secret file
    try:
        from .config import STACK_ROOT

        secret = STACK_ROOT / ".agent-secrets" / "nvidia_key"
        if secret.exists():
            val = secret.read_text(encoding="utf-8").strip()
            if val:
                return val
    except OSError:
        pass
    except Exception:
        pass
    return (getattr(cfg, "api_key", "") or "").strip()


def nvidia_available(cfg: Any) -> bool:
    """True iff a NVIDIA API key resolves (engine may still be 'local')."""
    return bool(resolve_api_key(cfg))


class NvidiaClient:
    """Thin OpenAI-compatible client for the NVIDIA Build API."""

    def __init__(
        self,
        cfg: Any,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.cfg = cfg
        self.base = str(getattr(cfg, "base_url", "")).rstrip("/") or "https://integrate.api.nvidia.com/v1"
        self.timeout = getattr(cfg, "timeout_seconds", 120)
        # Text LLM offload timeout. The throttle (below) prevents free-tier burst
        # 529s, but under load deepseek-v4-pro can exceed 30s; give it the full
        # configured window (default 120s) so the strong hosted model gets a real
        # chance instead of timing out and silently falling back to local qwen3:8b.
        self.llm_timeout = max(self.timeout, 30)
        self.api_key = resolve_api_key(cfg)
        # Free-tier rate-limit throttle: the NVIDIA Build tier 529s / times out
        # on BURST calls (2-3 rapid calls then Overloaded). Pipeline LLM stages
        # make many sequential calls, so space them out to stay under the burst
        # limit and let the strong hosted models (deepseek-v4-pro etc.) be used
        # instead of falling back to local qwen3:8b. Verified: 6 calls with 8s
        # spacing -> all succeed in 1-7s; burst -> 529 on the 2nd/3rd call.
        self.min_interval = getattr(cfg, "min_interval", 6.0)
        self._last_call = 0.0
        self.session = session or requests.Session()

    def _throttle(self) -> None:
        """Enforce a minimum interval between calls to avoid free-tier burst
        rate-limiting. Returns immediately if enough time has passed."""
        wait = self.min_interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def ready(self) -> bool:
        if _circuit_open():
            return False
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _image_data_uri(self, image: Path | bytes) -> str:
        raw = image if isinstance(image, bytes) else Path(image).read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        mime = "image/png"
        if raw.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a"):
            mime = "image/gif"
        elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            mime = "image/webp"
        return f"data:{mime};base64,{b64}"

    # ---- LLM text -----------------------------------------------------------

    def chat(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 3000,
    ) -> str | None:
        """One-shot text completion. Returns text or None on failure."""
        if not self.ready():
            return None
        model = model or getattr(self.cfg, "text_model", "") or DEFAULT_TEXT_MODEL
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            self._throttle()
            resp = self.session.post(
                f"{self.base}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self.llm_timeout,
            )
            if resp.status_code in (429, 529):
                _circuit_record(True)
                logger.warning("nvidia chat rate-limited (%s); local fallback", resp.status_code)
                return None
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"].get("content")
            # Reasoning models (deepseek) return content=None until the final
            # answer; surface the reasoning as a fallback so callers get text.
            if not content:
                content = data["choices"][0]["message"].get("reasoning_content")
            _circuit_record(False)
            return content or None
        except requests.RequestException as exc:
            _circuit_record(True)
            logger.warning("nvidia chat failed; local fallback: %s", exc)
            return None
        except (KeyError, IndexError, ValueError) as exc:
            _circuit_record(True)
            logger.warning("nvidia chat malformed; local fallback: %s", exc)
            return None

    # ---- vision QC -----------------------------------------------------------

    def judge_vision(
        self,
        prompt: str,
        images: list[Path | bytes],
        *,
        system: str = "You are a strict, precise anime-video production QC judge.",
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str | None:
        """Send a vision judge request. Returns text or None on failure."""
        if not self.ready():
            return None
        model = model or getattr(self.cfg, "vision_model", "") or DEFAULT_VISION_MODEL
        user_content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in images:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": self._image_data_uri(img)},
            })
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            self._throttle()
            resp = self.session.post(
                f"{self.base}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            if resp.status_code in (429, 529):
                _circuit_record(True)
                logger.warning("nvidia vision rate-limited (%s); local fallback", resp.status_code)
                return None
            resp.raise_for_status()
            _circuit_record(False)
            return resp.json()["choices"][0]["message"].get("content")
        except requests.RequestException as exc:
            _circuit_record(True)
            logger.warning("nvidia vision failed; local fallback: %s", exc)
            return None
        except (KeyError, IndexError, ValueError) as exc:
            _circuit_record(True)
            logger.warning("nvidia vision malformed; local fallback: %s", exc)
            return None

    # ---- image generation (best-effort) --------------------------------------

    def generate_image(
        self,
        prompt: str,
        out_path: Path,
        *,
        width: int = 1024,
        height: int = 1024,
        model: str | None = None,
        max_retries: int = 2,
    ) -> bool:
        """Generate an image to ``out_path`` via the NVIDIA API.

        The hosted diffusiongemma model plans a ``dalle.text2im`` action rather
        than returning the raster directly, and realising it needs the separate
        ``ai.api.nvidia.com/v1/genai`` host. This method attempts the plan and
        returns False when it cannot produce pixels, so the caller falls back to
        local ComfyUI without breaking the stage.
        """
        if not self.ready():
            return False
        model = model or getattr(self.cfg, "image_model", "") or DEFAULT_IMAGE_MODEL
        if model not in _SUPPORTED_IMAGE_MODELS:
            logger.warning("nvidia image model %r unsupported; local fallback", model)
            return False
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1200,
        }
        try:
            self._throttle()
            resp = self.session.post(
                f"{self.base}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            plan = resp.json()["choices"][0]["message"].get("content") or ""
            action_input = self._extract_text2im_prompt(plan)
            if not action_input:
                logger.warning("nvidia image: no dalle.text2im plan produced; local fallback")
                return False
            # The OpenAI-compatible integrate host does not execute image gen;
            # try the NVIDIA genai host if an endpoint is configured.
            genai = self._try_genai_host(action_input)
            if genai is None:
                logger.warning(
                    "nvidia image: genai host not configured/available; "
                    "save the planned prompt and fall back to local ComfyUI"
                )
                out_path.write_text(
                    "NVIDIA image plan (not rendered locally):\n" + plan, encoding="utf-8"
                )
                return False
            out_path.write_bytes(genai)
            return True
        except requests.RequestException as exc:
            logger.warning("nvidia image failed; local fallback: %s", exc)
            return False
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning("nvidia image malformed; local fallback: %s", exc)
            return False

    @staticmethod
    def _extract_text2im_prompt(plan: str) -> str | None:
        """Parse the model's ``dalle.text2im`` JSON for the actual prompt."""
        try:
            block = json.loads(plan)
        except (ValueError, TypeError):
            block = None
        if isinstance(block, dict) and block.get("action") == "dalle.text2im":
            ai = block.get("action_input")
            if isinstance(ai, str):
                try:
                    return json.loads(ai).get("prompt")
                except (ValueError, TypeError):
                    return ai
            if isinstance(ai, dict):
                return ai.get("prompt")
        return None

    def _try_genai_host(self, action_input: str) -> bytes | None:
        """Best-effort: POST the planned prompt to a configured genai host."""
        host = getattr(self.cfg, "genai_url", "") or ""
        if not host:
            return None
        try:
            resp = self.session.post(
                host.rstrip("/") + "/image",
                json={"prompt": action_input},
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return base64.b64decode(data["data"][0]["b64_json"])
        except (requests.RequestException, KeyError, IndexError, ValueError):
            return None
