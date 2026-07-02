from fastapi import APIRouter
from app.config.loader import ConfigLoader

router = APIRouter()


@router.get("/health")
async def health_check():
    models = list(ConfigLoader.get_all_models().keys())
    agents = list(ConfigLoader.get_all_agents().keys())
    return {
        "status": "ok",
        "service": "agent-atlas",
        "models_loaded": len(models),
        "agents_loaded": len(agents),
    }
