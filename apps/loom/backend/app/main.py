"""
main.py  --  FastAPI entrypoint.

Route layout mirrors the previous version so nothing outside this app
(the dashboard, start.bat, llm-wiki-workflow's bridge tools) needs to
change: everything lives under /api, health/run have no extra prefix,
agents/jobs are prefixed with their own name. /ws stays at root (not
under /api) for a simpler client URL. /mcp/sse (MCP server) is added in
a later build phase.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents import background_runtime
from app.agents.base import set_trace_hook
from app.agents.registry import register_all
from app.api import agents, health, jobs, llm, obsidian, run
from app.api import ws as ws_api
from app.api.mcp_server import mcp as mcp_server
from app.config.loader import ConfigLoader
from app.services import collaboration_bus as bus
from app.services import ws_bus
from app.services.langfuse_client import trace_agent_call
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
    bus.set_broadcast_hook(ws_bus.broadcast)
    set_trace_hook(trace_agent_call)
    background_runtime.start_workers(n=2)
    logger.info(
        "Loom starting: %d models, %d agent configs, %d handlers registered",
        len(ConfigLoader.get_all_models()), len(ConfigLoader.get_all_agents()), registered,
    )
    yield
    await background_runtime.stop_workers()
    logger.info("Loom shutting down")


app = FastAPI(title="Loom", lifespan=lifespan)

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
api.include_router(obsidian.router, prefix="/obsidian", tags=["obsidian"])
api.include_router(llm.router, prefix="/llm", tags=["llm"])
app.include_router(api)
app.include_router(ws_api.router)
app.mount("/mcp", mcp_server.sse_app())

if FRONTEND_DIST.exists():
    # StaticFiles alone only serves index.html for "/" -- a direct load or
    # refresh on a client-side route like /agents or /jobs/abc123 would
    # 404 (there's no such file on disk; React Router only handles it
    # once index.html's JS is already running). Assets get their own real
    # files mount; everything else that isn't /api, /ws, or /mcp falls
    # through to index.html so React Router can take over.
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend-assets")
    _INDEX_HTML = FRONTEND_DIST / "index.html"

    @app.get("/{full_path:path}")
    async def _frontend_fallback(full_path: str):
        requested = FRONTEND_DIST / full_path
        if full_path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(_INDEX_HTML)
else:
    @app.get("/")
    async def _no_frontend():
        return {
            "status": "ok",
            "note": "frontend/dist not built yet -- run `npm run build` in "
                    "apps/loom/frontend, or use /api/health to check "
                    "the backend directly.",
        }
