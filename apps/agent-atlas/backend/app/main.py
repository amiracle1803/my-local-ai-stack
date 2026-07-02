"""
main.py  --  FastAPI entrypoint.

Route layout mirrors the previous version so nothing outside this app
(the dashboard, start.bat, llm-wiki-workflow's bridge tools) needs to
change: everything lives under /api, health/run have no extra prefix,
agents/jobs are prefixed with their own name.

/ws (WebSocket bus) and /mcp/sse (MCP server) are added in a later build
phase -- not mounted yet, so there's no half-built route sitting here in
the meantime.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agents.registry import register_all
from app.api import agents, health, jobs, run
from app.config.loader import ConfigLoader
from app.storage.database import init_db
from app.utils.logging import setup_logging

logger = logging.getLogger("agent_atlas.main")

FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    ConfigLoader.load()
    registered = register_all()
    logger.info(
        "Agent Atlas starting: %d models, %d agent configs, %d handlers registered",
        len(ConfigLoader.get_all_models()), len(ConfigLoader.get_all_agents()), registered,
    )
    yield
    logger.info("Agent Atlas shutting down")


app = FastAPI(title="Agent Atlas", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")
api.include_router(health.router)
api.include_router(run.router)
api.include_router(agents.router, prefix="/agents", tags=["agents"])
api.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(api)

if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/")
    async def _no_frontend():
        return {
            "status": "ok",
            "note": "frontend/dist not built yet -- run `npm run build` in "
                    "apps/agent-atlas/frontend, or use /api/health to check "
                    "the backend directly.",
        }
