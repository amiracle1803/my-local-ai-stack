"""
model_router.py  --  Pick an available model and call it.

Providers are OpenAI-compatible (Ollama, LM Studio, and Groq all speak the
same /chat/completions shape), so one small httpx-based client handles all
of them -- no need for the `openai` SDK as a dependency.

get_best_client() probes in order: the agent's own model_preference list,
then models.yml's global discovery_order, then whatever's left. Local
providers are probed with a real GET to their /models endpoint; Groq is
"available" if GROQ_API_KEY is set (no network probe -- avoid a remote
call just to check a local capability list). Results are cached for 45s
so a busy period doesn't hammer Ollama with health checks between every
agent call.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from app.config.loader import ConfigLoader, ModelConfig

logger = logging.getLogger("agent_atlas.model_router")

_AVAILABILITY_CACHE: Dict[str, tuple[bool, float]] = {}
_CACHE_TTL_S = 45.0


class ModelUnavailableError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, config: ModelConfig):
        self.config = config

    async def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> Dict[str, Any]:
        headers = {}
        if self.config.api_key_env:
            key = os.getenv(self.config.api_key_env)
            if not key:
                raise ModelUnavailableError(
                    f"{self.config.name}: {self.config.api_key_env} is not set"
                )
            headers["Authorization"] = f"Bearer {key}"

        body = {
            "model": self.config.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }
        async with httpx.AsyncClient(timeout=kwargs.get("timeout", 60.0)) as client:
            resp = await client.post(self.config.endpoint, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"] or ""
        return {"content": content.strip(), "model": self.config.name, "raw": data}


def _models_base_url(endpoint: str) -> Optional[str]:
    """http://host:port/v1/chat/completions -> http://host:port/v1/models"""
    if endpoint.endswith("/chat/completions"):
        return endpoint[: -len("/chat/completions")] + "/models"
    return None


async def _probe(config: ModelConfig) -> bool:
    cached = _AVAILABILITY_CACHE.get(config.name)
    if cached and (time.monotonic() - cached[1]) < _CACHE_TTL_S:
        return cached[0]

    ok = False
    try:
        if config.provider == "groq":
            ok = bool(config.api_key_env and os.getenv(config.api_key_env))
        elif config.endpoint:
            models_url = _models_base_url(config.endpoint)
            if models_url:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(models_url)
                    ok = resp.status_code == 200
    except Exception as exc:  # noqa: BLE001
        logger.debug("probe failed for %s: %s", config.name, exc)
        ok = False

    _AVAILABILITY_CACHE[config.name] = (ok, time.monotonic())
    return ok


async def get_best_client(preferred: Optional[List[str]] = None) -> ModelClient:
    routing = ConfigLoader.routing()
    candidates: List[str] = []
    for name in (preferred or []):
        if name not in candidates:
            candidates.append(name)
    for name in routing.discovery_order:
        if name not in candidates:
            candidates.append(name)
    for name in ConfigLoader.get_all_models():
        if name not in candidates:
            candidates.append(name)

    tried = []
    for name in candidates:
        config = ConfigLoader.get_model(name)
        if config is None:
            continue
        tried.append(name)
        if await _probe(config):
            return ModelClient(config)

    raise ModelUnavailableError(
        f"No model available (tried: {', '.join(tried) or 'none configured'}). "
        f"Start Ollama (`ollama serve`) or LM Studio, or set GROQ_API_KEY."
    )
