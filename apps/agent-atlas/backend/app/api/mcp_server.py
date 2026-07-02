"""
mcp_server.py  --  Expose Agent Atlas as an MCP server (SSE, at /mcp/sse)
for external clients: Claude Desktop, Claude Code, Cursor.

Deliberately a SHORTER tool list than the old version's ~19 tools.
Dropped web_fetch/web_search and the n8n_* CRUD tools -- those are now
handled by knowledge_hub/automation_agent calling out to Docker's
cataloged MCP servers (Phase 3c/3d) instead of Agent Atlas hand-rolling
its own versions. What's left here is what only Agent Atlas itself can
do: run its orchestrator, search its own indexed vault, manage its own
job queue, list its own agents, draft (not execute) n8n workflows using
its own automation_agent. No email tools -- that integration wasn't
built in this rebuild, so no point exposing a tool with nothing behind
it.
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

from app.config.loader import ConfigLoader
from app.services import collaboration_bus as bus
from app.services.collaboration_bus import NoHandlerError
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.mcp_server")

mcp = FastMCP(
    "agent-atlas",
    instructions="Local multi-agent system: orchestration, background jobs, "
                 "and semantic search over an Obsidian vault.",
)


@mcp.tool()
async def ask_atlas(goal: str) -> str:
    """Ask Agent Atlas's orchestrator to answer a goal directly and synchronously."""
    try:
        result = await bus.send_message(from_agent="mcp", to_agent="orchestrator",
                                         msg_type="run", payload={"goal": goal, "context": {}})
        return str(result)
    except NoHandlerError:
        return "Error: orchestrator isn't available right now."


@mcp.tool()
async def list_agents() -> str:
    """List all registered Agent Atlas agents, grouped by layer."""
    agents = ConfigLoader.get_all_agents()
    by_layer: dict[str, list[str]] = {}
    for a in agents.values():
        by_layer.setdefault(a.get("layer", "unknown"), []).append(a["id"])
    return json.dumps(by_layer, indent=2)


@mcp.tool()
async def search_knowledge(query: str) -> str:
    """Search both the Obsidian vault and the live web (if configured) for a query."""
    try:
        result = await bus.send_message(from_agent="mcp", to_agent="knowledge_hub",
                                         msg_type="search", payload={"query": query})
        return json.dumps(result, default=str)
    except NoHandlerError:
        return "Error: knowledge_hub isn't available."


@mcp.tool()
async def search_obsidian(query: str) -> str:
    """Search only the Obsidian vault (semantic search over indexed notes)."""
    try:
        result = await bus.send_message(from_agent="mcp", to_agent="obsidian_brain",
                                         msg_type="search", payload={"query": query})
        return json.dumps(result, default=str)
    except NoHandlerError:
        return "Error: obsidian_brain isn't available."


@mcp.tool()
async def create_background_job(goal: str) -> str:
    """Queue a goal as a background job. Returns a job_id -- check progress with check_job."""
    job_id = new_id()
    ts = now_iso()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO jobs (id, type, title, status, payload_json, progress, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (job_id, "compose_task", goal[:120], "queued",
             json.dumps({"goal": goal, "context": {}}), 0.0, ts, ts),
        )
        conn.commit()
    finally:
        conn.close()
    return job_id


@mcp.tool()
async def check_job(job_id: str) -> str:
    """Check a background job's status and result by id."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT status, result_json, error FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return f"No job found with id {job_id}"
    return json.dumps({
        "status": row["status"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": row["error"],
    })


@mcp.tool()
async def draft_n8n_workflow(goal: str) -> str:
    """Draft a plain-English plan for an n8n workflow that would accomplish a goal.
    Does not create or run anything -- planning only."""
    try:
        result = await bus.send_message(from_agent="mcp", to_agent="automation_agent",
                                         msg_type="draft_workflow", payload={"goal": goal})
        return json.dumps(result, default=str)
    except NoHandlerError:
        return "Error: automation_agent isn't available."
