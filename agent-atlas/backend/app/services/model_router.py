"""
Auto-discovery model router.

Priority order comes from config/models.yml routing.discovery_order.
Each candidate is probed (with a 45s result cache) and the first reachable
one is returned. This means:
  - Ollama running locally   → picked automatically
  - LM Studio open           → picked automatically
  - Neither running          → falls through to Groq cloud (if key set)
  - Nothing available        → helpful RuntimeError with instructions
"""
import asyncio
import logging
import os
import time
from typing import Dict, Optional, Tuple

import httpx

from app.config.loader import ConfigLoader
from app.services.llm_clients import ModelClient, build_client

logger = logging.getLogger("agent_atlas.router")

# Availability cache: model_name → (available, timestamp)
_cache: Dict[str, Tuple[bool, float]] = {}
_CACHE_TTL = 45.0  # seconds before re-probing an endpoint


async def _probe(model_name: str) -> bool:
    """Return True if the model is reachable AND the specific model is loaded."""
    config = ConfigLoader.get_model(model_name)
    if not config:
        return False

    if config.provider == "local":
        health_url = (config.endpoint or "").replace("/chat/completions", "/models")
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(health_url)
            if r.status_code >= 500:
                return False

            # Verify the specific model is actually loaded, not just the endpoint alive
            try:
                data = r.json()
                loaded = data.get("data", [])
                if not loaded:
                    logger.debug("Probe %s: endpoint alive but no models loaded", model_name)
                    return False
                if config.model:
                    want = config.model.lower()
                    ids = [m.get("id", "").lower() for m in loaded]
                    found = any(want in mid or mid in want for mid in ids)
                    if not found:
                        logger.debug(
                            "Probe %s: model '%s' not in loaded list %s",
                            model_name, config.model, ids,
                        )
                    return found
                return True  # endpoint alive, no model name constraint
            except Exception:
                # Can't parse model list — assume endpoint is usable
                return r.status_code < 500
        except Exception:
            return False

    if config.provider == "groq":
        return bool(os.getenv(config.api_key_env or "GROQ_API_KEY", ""))

    return False


async def get_best_client(preferred: Optional[list] = None) -> ModelClient:
    """
    Auto-discover and return the best available ModelClient.

    Search order:
      1. preferred list (agent's model_preference from YAML)
      2. discovery_order from models.yml routing section
      3. Any remaining configured models

    Availability is cached for 45 s per model to avoid hammering endpoints.
    """
    now = time.monotonic()
    routing = ConfigLoader.get_routing()

    candidates: list[str] = []
    seen: set[str] = set()

    def _add(name: str):
        if name not in seen:
            candidates.append(name)
            seen.add(name)

    for name in (preferred or []):
        _add(name)
    for name in routing.discovery_order:
        _add(name)
    for name in ConfigLoader.get_all_models():
        _add(name)

    for name in candidates:
        cached = _cache.get(name)
        if cached is not None:
            available, ts = cached
            if now - ts < _CACHE_TTL:
                if available:
                    client = build_client(name)
                    if client:
                        logger.debug("Router: using cached-available %s", name)
                        return client
                continue  # known unavailable, skip until TTL expires

        # Cache miss or stale — probe now
        available = await _probe(name)
        _cache[name] = (available, now)

        if available:
            client = build_client(name)
            if client:
                logger.info("Router: selected %s", name)
                return client
        else:
            logger.debug("Router: %s not reachable", name)

    raise RuntimeError(
        "No LLM available. Options (in priority order):\n"
        "  1. Start Ollama:      ollama serve   (free, runs in background)\n"
        "  2. Open LM Studio with a model loaded\n"
        "  3. Set GROQ_API_KEY in .env          (free at console.groq.com)\n"
        "     Then deploy to Railway/Fly.io to run 24/7 without your PC"
    )


def invalidate_cache(model_name: Optional[str] = None):
    """Force re-probe on next request."""
    if model_name:
        _cache.pop(model_name, None)
    else:
        _cache.clear()


class ModelRouter:
    """
    Synchronous rule-based router that maps task properties to a ModelClient.
    Used by agents and tests; async auto-discovery is handled by get_best_client().
    """

    def choose(self, task) -> ModelClient:
        """
        Select a ModelClient based on task privacy, difficulty, and config flags.
        Routing rules (first match wins):
          1. private task OR remote disabled → local only
          2. requires live web AND search allowed → perplexity
          3. hard task AND remote allowed → claude
          4. default → local
        """
        routing = ConfigLoader.get_routing()
        local_only = os.getenv("LOCAL_ONLY", "false").lower() in ("1", "true", "yes")
        allow_remote = routing.allow_remote_models and not local_only

        privacy = getattr(task, "privacy_level", "mixed")
        if privacy == "private" or not allow_remote:
            client = self._pick_local()
            if client:
                return client
            raise RuntimeError("No local model available")

        if getattr(task, "requires_fresh_web", False) and routing.allow_remote_search:
            client = build_client("perplexity_pro")
            if client:
                return client

        if getattr(task, "difficulty", "normal") == "hard":
            client = build_client("claude_pro")
            if client:
                return client

        client = self._pick_local()
        if client:
            return client
        raise RuntimeError("No local model available")

    def _pick_local(self) -> Optional[ModelClient]:
        for name in ConfigLoader.get_all_models():
            cfg = ConfigLoader.get_model(name)
            if cfg and cfg.provider == "local":
                client = build_client(name)
                if client:
                    return client
        return None
