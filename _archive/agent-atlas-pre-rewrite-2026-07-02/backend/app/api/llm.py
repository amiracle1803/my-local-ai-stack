import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config.loader import ConfigLoader
from app.services.llm_clients import build_client, is_model_available
from app.services.model_router import get_best_client

logger = logging.getLogger("agent_atlas.api.llm")
router = APIRouter()


class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None


@router.post("/chat")
async def chat(req: ChatRequest):
    if req.model:
        client = build_client(req.model)
        if not client:
            raise HTTPException(status_code=404, detail=f"Model '{req.model}' not found or unavailable")
    else:
        try:
            client = await get_best_client()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
    kwargs = {}
    if req.max_tokens:
        kwargs["max_tokens"] = req.max_tokens
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    try:
        return await client.chat(req.messages, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/test")
async def test_llm():
    """Smoke-test: auto-discover the best available model and send a short prompt."""
    try:
        client = await get_best_client()
        result = await client.chat(
            [{"role": "user", "content": "Say 'Agent Atlas online' and nothing else."}],
            max_tokens=20,
        )
        return {"status": "ok", "response": result["content"], "model": result.get("model")}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/models")
async def list_models():
    models = ConfigLoader.get_all_models()
    return [
        {
            "name": k,
            "provider": v.provider,
            "capabilities": v.capabilities,
            "available": is_model_available(k),
        }
        for k, v in models.items()
    ]


@router.get("/debug/endpoints")
async def debug_endpoints():
    """Show exactly what model IDs each local endpoint is reporting.
    Use this to verify your models.yml model names match what's loaded.
    """
    results = []
    for name, cfg in ConfigLoader.get_all_models().items():
        if cfg.provider != "local" or not cfg.endpoint:
            continue
        models_url = cfg.endpoint.replace("/chat/completions", "/models")
        entry: dict = {"config_name": name, "config_model": cfg.model, "endpoint": cfg.endpoint, "loaded_models": [], "error": None}
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(models_url)
            if r.status_code == 200:
                entry["loaded_models"] = [m.get("id") for m in r.json().get("data", [])]
            else:
                entry["error"] = f"HTTP {r.status_code}"
        except Exception as exc:
            entry["error"] = str(exc)
        results.append(entry)
    return results
