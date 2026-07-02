from fastapi import APIRouter

from app.config.loader import ConfigLoader

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "agent-atlas",
        "models_loaded": len(ConfigLoader.get_all_models()),
        "agents_loaded": len(ConfigLoader.get_all_agents()),
    }
