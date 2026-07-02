import logging
import os
import time
from typing import Any, ClassVar, Dict, List, Optional, Tuple

import httpx

from app.config.loader import ConfigLoader, ModelConfig

logger = logging.getLogger("agent_atlas.llm")

Message = Dict[str, Any]


class ModelClient:
    async def chat(self, messages: List[Message], **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError


class HermesLocalClient(ModelClient):
    """OpenAI-compatible local endpoint (Ollama / LM Studio / llama.cpp).

    Auto-resolves the actual loaded model ID from /v1/models before each
    request so the model field always matches what the server has loaded,
    preventing 400 errors from name mismatches (e.g. LM Studio appends
    quantization suffixes that differ from the config value).
    """

    # Class-level cache: endpoint → (resolved_model_id, timestamp)
    _model_id_cache: ClassVar[Dict[str, Tuple[str, float]]] = {}
    _MODEL_ID_TTL = 60.0  # re-fetch after 60 s (catches model swaps in LM Studio)

    def __init__(self, config: ModelConfig):
        self.config = config
        self.endpoint = config.endpoint or "http://127.0.0.1:11434/v1/chat/completions"
        self._models_url = self.endpoint.replace("/chat/completions", "/models")

    async def _resolve_model_id(self) -> str:
        """Return the actual model ID currently loaded at this endpoint."""
        now = time.monotonic()
        cached = self._model_id_cache.get(self.endpoint)
        if cached:
            model_id, ts = cached
            if now - ts < self._MODEL_ID_TTL:
                return model_id

        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(self._models_url)
            if r.status_code == 200:
                loaded = r.json().get("data", [])
                if loaded:
                    want = (self.config.model or "").lower()
                    # Try substring match first (handles suffix differences)
                    if want:
                        for m in loaded:
                            mid = m.get("id", "")
                            if want in mid.lower() or mid.lower() in want:
                                self._model_id_cache[self.endpoint] = (mid, now)
                                logger.debug("Resolved model '%s' → '%s'", want, mid)
                                return mid
                    # No config model or no match — use whatever is loaded
                    first = loaded[0].get("id", self.config.model or "")
                    self._model_id_cache[self.endpoint] = (first, now)
                    logger.debug("No match for '%s'; using first loaded model: %s", want, first)
                    return first
        except Exception as exc:
            logger.debug("Could not fetch /models from %s: %s", self._models_url, exc)

        # Fall back to configured model name (may still cause 400, but we tried)
        return self.config.model or ""

    async def chat(self, messages: List[Message], **kwargs: Any) -> Dict[str, Any]:
        model_id = await self._resolve_model_id()
        payload: Dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(self.endpoint, json=payload)

                # Some LM Studio builds reject max_tokens — retry without it
                if resp.status_code == 400:
                    body_preview = resp.text[:300]
                    logger.warning(
                        "400 from %s (model=%s). Retrying without max_tokens. Body: %s",
                        self.endpoint, model_id, body_preview,
                    )
                    payload.pop("max_tokens", None)
                    # Also clear cached model ID so next call re-probes
                    self._model_id_cache.pop(self.endpoint, None)
                    resp = await client.post(self.endpoint, json=payload)

                if resp.status_code == 404:
                    from app.services.model_router import invalidate_cache
                    invalidate_cache(self.config.name)
                    raise RuntimeError(
                        f"Model '{model_id}' not found at {self.endpoint}. "
                        f"For Ollama: run `ollama pull {self.config.model}`"
                    )

                # Convert any remaining HTTP error to RuntimeError so the
                # retry loop in BaseAgent.llm_call() can catch and retry it.
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as http_err:
                    body = http_err.response.text[:400] if http_err.response else ""
                    raise RuntimeError(
                        f"LLM HTTP {http_err.response.status_code} from {self.endpoint} "
                        f"(model={model_id}): {body}"
                    ) from http_err

                data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError(
                    f"LLM at {self.endpoint} returned no choices. Full response: {str(data)[:400]}"
                )
            message = choices[0].get("message", {})
            content = message.get("content")
            if content is None:
                raise RuntimeError(
                    f"LLM at {self.endpoint} returned a choice with no 'content'. "
                    f"Choice: {str(choices[0])[:300]}"
                )
            return {"content": content, "model": self.config.name, "raw": data}
        except httpx.ConnectError:
            raise RuntimeError(
                f"Local LLM unreachable at {self.endpoint}. "
                "Start Ollama (`ollama serve`) or LM Studio."
            )


class GroqClient(ModelClient):
    """Groq cloud inference — free tier, OpenAI-compatible. Works 24/7."""

    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, config: ModelConfig):
        self.config = config
        self.api_key = os.getenv(config.api_key_env or "GROQ_API_KEY", "")

    async def chat(self, messages: List[Message], **kwargs: Any) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY not set — add it to .env")
        payload = {
            "model": self.config.model or "llama-3.3-70b-versatile",
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=headers)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as http_err:
                body = http_err.response.text[:400] if http_err.response else ""
                raise RuntimeError(
                    f"Groq HTTP {http_err.response.status_code}: {body}"
                ) from http_err
            data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(
                f"Groq returned no choices. Full response: {str(data)[:400]}"
            )
        content = choices[0].get("message", {}).get("content")
        if content is None:
            raise RuntimeError(
                f"Groq choice missing 'content'. Choice: {str(choices[0])[:300]}"
            )
        return {"content": content, "model": self.config.name, "raw": data}


def build_client(model_name: str) -> Optional[ModelClient]:
    """Instantiate the right client for a model name. Returns None if unavailable."""
    config = ConfigLoader.get_model(model_name)
    if not config:
        logger.debug("No model config for '%s'", model_name)
        return None
    if config.provider == "local":
        return HermesLocalClient(config)
    if config.provider == "groq":
        key = os.getenv(config.api_key_env or "GROQ_API_KEY", "")
        if not key:
            logger.debug("Skipping %s — GROQ_API_KEY not set", model_name)
            return None
        return GroqClient(config)
    logger.warning("Unknown provider '%s' for model '%s'", config.provider, model_name)
    return None


def is_model_available(name: str) -> bool:
    """Quick sync availability check (no network call — checks config + keys only)."""
    config = ConfigLoader.get_model(name)
    if not config:
        return False
    if config.provider == "local":
        return True  # actual reachability checked at call time
    if config.provider == "groq":
        return bool(os.getenv(config.api_key_env or "GROQ_API_KEY", ""))
    return False
