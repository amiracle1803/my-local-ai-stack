from typing import Any, Dict, List

from fastapi import APIRouter

from app.config.loader import ConfigLoader
from app.services.model_router import _probe

router = APIRouter()


@router.get("/models")
async def list_models() -> List[Dict[str, Any]]:
    models = ConfigLoader.get_all_models()
    result = []
    for name, config in models.items():
        available = await _probe(config)
        result.append({
            "name": name,
            "provider": config.provider,
            "capabilities": config.capabilities,
            "available": available,
        })
    return result
