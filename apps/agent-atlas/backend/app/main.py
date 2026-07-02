import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter
from fastapi.staticfiles import StaticFiles

# Load .env before any service imports
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"
load_dotenv(_ENV_FILE, override=True)

from app.api import health, agents, jobs, llm, obsidian, run, metrics, system
from app.api import ws as ws_router
from app.api.mcp_server import mcp_server
from app.config.loader import load_config
from app.storage.database import init_db
from app.agents.registry import register_all_agents
from app.agents.background_runtime import start_worker, stop_worker
from app.services.policy_engine import load_policies
from app.services.health_watchdog import start_watchdog, stop_watchdog
from app.services.db_backup import start_backup_scheduler, stop_backup_scheduler
from app.utils.logging import setup_logging

logger = logging.getLogger("agent_atlas")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting Agent Atlas...")
    init_db()
    load_config()
    register_all_agents()
    load_policies()
    start_worker()        # background job workers
    start_watchdog()      # probe model endpoints every 60 s
    start_backup_scheduler()  # daily SQLite export

    # ── Obsidian vault: mandatory memory store ────────────────────────────────
    from app.services.obsidian_indexer import get_vault_path, ensure_vault_structure, index_vault
    vault = get_vault_path()
    if vault:
        ensure_vault_structure()
        import asyncio
        # Run indexing in thread so it doesn't block startup
        loop = asyncio.get_running_loop()
        indexed = await loop.run_in_executor(None, index_vault, vault)
        logger.info("Obsidian vault indexed: %d notes  (%s)", indexed, vault)
    else:
        logger.warning(
            "OBSIDIAN_VAULT_PATH not set or path does not exist — "
            "agents will have no persistent memory. Set it in .env."
        )

    logger.info("Agent Atlas ready.")
    yield
    stop_backup_scheduler()
    stop_watchdog()
    stop_worker()
    logger.info("Shutting down Agent Atlas.")


app = FastAPI(
    title="Agent Atlas",
    version="0.2.0",
    description="Local-first multi-agent system — auto-discovers Ollama, LM Studio, or Groq",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── All API routes live under /api ────────────────────────────────────────────
api = APIRouter(prefix="/api")
api.include_router(health.router)
api.include_router(run.router)
api.include_router(agents.router, prefix="/agents", tags=["agents"])
api.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api.include_router(llm.router, prefix="/llm", tags=["llm"])
api.include_router(obsidian.router, prefix="/obsidian", tags=["obsidian"])
api.include_router(metrics.router, tags=["metrics"])
api.include_router(system.router)
app.include_router(api)

# WebSocket stays at root (not under /api — browser WS URL is simpler)
app.include_router(ws_router.router)

# ── MCP server (Model Context Protocol) ──────────────────────────────────────
# Claude Desktop / Claude Code / VS Code / Cursor connect to:
#   http://127.0.0.1:8000/mcp/sse
# Must be mounted BEFORE the StaticFiles catch-all below.
app.mount("/mcp", mcp_server.sse_app())
logger.info("MCP server mounted at /mcp/sse")

# ── Serve built frontend in production (Docker / Railway / Fly.io) ────────────
_FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
    logger.info("Serving frontend from %s", _FRONTEND_DIST)
