import yaml
import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from app.config.loader import ConfigLoader
from app.models.agent import AgentCreateRequest, AgentDefinition

logger = logging.getLogger("agent_atlas.api.agents")
router = APIRouter()

CONFIG_AGENTS_DIR = Path(__file__).parent.parent.parent.parent / "config" / "agents"


@router.get("/", response_model=List[Dict[str, Any]])
async def list_agents():
    from app.services import collaboration_bus as bus

    agents = ConfigLoader.get_all_agents()
    return [
        {**a, "deletable": not bus.has_handler(a["id"])}
        for a in agents.values()
    ]


@router.get("/{agent_id}", response_model=Dict[str, Any])
async def get_agent(agent_id: str):
    agent = ConfigLoader.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return agent


@router.post("/{agent_id}/ping")
async def ping_agent(agent_id: str):
    """Send a minimal test prompt through the bus to verify the agent responds."""
    import asyncio
    from app.services import collaboration_bus as bus
    from app.utils.ids import now_iso
    import time

    agent = ConfigLoader.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    _PING_TIMEOUT = 30.0  # agents should respond well within 30 s

    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            bus.send_message(
                from_agent="system",
                to_agent=agent_id,
                msg_type="ping",
                payload={"goal": "Reply with exactly: PONG", "context": {}},
            ),
            timeout=_PING_TIMEOUT,
        )
        latency_ms = round((time.monotonic() - start) * 1000)
        return {
            "agent_id": agent_id,
            "status": "ok",
            "latency_ms": latency_ms,
            "response": str(result)[:200] if result else "",
            "checked_at": now_iso(),
        }
    except asyncio.TimeoutError:
        latency_ms = round((time.monotonic() - start) * 1000)
        return {
            "agent_id": agent_id,
            "status": "error",
            "latency_ms": latency_ms,
            "error": f"Timed out after {_PING_TIMEOUT:.0f}s",
            "checked_at": now_iso(),
        }
    except Exception as exc:
        latency_ms = round((time.monotonic() - start) * 1000)
        return {
            "agent_id": agent_id,
            "status": "error",
            "latency_ms": latency_ms,
            "error": str(exc),
            "checked_at": now_iso(),
        }


@router.post("/factory", status_code=201)
async def create_agent(req: AgentCreateRequest):
    """Agent Factory: write a new agent YAML config and reload registry."""
    agent_id = req.id  # already normalized and validated by the Pydantic model
    dest = CONFIG_AGENTS_DIR / f"{agent_id}.yml"
    # Defense-in-depth: confirm resolved path stays within config/agents/
    try:
        dest.resolve().relative_to(CONFIG_AGENTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID — path escapes config directory")
    if dest.exists():
        raise HTTPException(status_code=409, detail=f"Agent '{agent_id}' already exists")

    data = {
        "id": agent_id,
        "display_name": req.display_name,
        "layer": req.layer,
        "description": req.description,
        "inputs": [],
        "outputs": [],
        "tools": req.tools,
        "model_preference": req.model_preference,
        "memory_scopes": req.memory_scopes,
        "policies": req.policies,
        "system_prompt": req.system_prompt or f"You are the {req.display_name} agent.",
    }
    CONFIG_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    # Reload config so new agent is immediately available
    ConfigLoader.load()
    return {"status": "created", "agent_id": agent_id, "path": str(dest)}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    """
    Delete a Factory-created agent's config. Refuses to delete the built-in
    agents (orchestrator, planner, code_agent, etc.) -- those have real
    Python handler classes registered on the collaboration bus and the rest
    of the system assumes they exist; removing just the YAML would leave a
    handler with no config instead of actually removing the agent.
    """
    from app.services import collaboration_bus as bus

    agent = ConfigLoader.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    if bus.has_handler(agent_id):
        raise HTTPException(
            status_code=409,
            detail=f"'{agent_id}' is a built-in agent with a registered handler -- it can't be deleted.",
        )

    dest = CONFIG_AGENTS_DIR / f"{agent_id}.yml"
    try:
        dest.resolve().relative_to(CONFIG_AGENTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID — path escapes config directory")
    if not dest.exists():
        raise HTTPException(status_code=404, detail=f"No config file for '{agent_id}'")

    dest.unlink()
    ConfigLoader.load()
    return {"status": "deleted", "agent_id": agent_id}
