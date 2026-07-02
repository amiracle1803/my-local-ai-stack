import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

import yaml
from fastapi import APIRouter, HTTPException

from app.agents.registry import BUILTIN_AGENT_IDS, register_generic_agents
from app.config.loader import ConfigLoader
from app.models.agent import AgentCreateRequest
from app.models.message import AgentMessage
from app.services import collaboration_bus as bus
from app.utils.ids import now_iso

logger = logging.getLogger("agent_atlas.api.agents")
router = APIRouter()

CONFIG_AGENTS_DIR = Path(__file__).parent.parent.parent.parent / "config" / "agents"
_PING_TIMEOUT = 30.0


@router.get("/", response_model=List[Dict[str, Any]])
async def list_agents():
    agents = ConfigLoader.get_all_agents()
    return [
        {**a, "deletable": a["id"] not in BUILTIN_AGENT_IDS}
        for a in agents.values()
    ]


@router.get("/{agent_id}", response_model=Dict[str, Any])
async def get_agent(agent_id: str):
    agent = ConfigLoader.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return {**agent, "deletable": agent_id not in BUILTIN_AGENT_IDS}


@router.post("/{agent_id}/ping")
async def ping_agent(agent_id: str):
    agent = ConfigLoader.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

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
    except Exception as exc:  # noqa: BLE001
        latency_ms = round((time.monotonic() - start) * 1000)
        return {
            "agent_id": agent_id,
            "status": "error",
            "latency_ms": latency_ms,
            "error": str(exc),
            "checked_at": now_iso(),
        }


def _validated_dest(agent_id: str) -> Path:
    dest = CONFIG_AGENTS_DIR / f"{agent_id}.yml"
    try:
        dest.resolve().relative_to(CONFIG_AGENTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID -- path escapes config directory")
    return dest


@router.post("/factory", status_code=201)
async def create_agent(req: AgentCreateRequest):
    """Agent Factory: write a new agent YAML config and reload registry."""
    dest = _validated_dest(req.id)
    if dest.exists():
        raise HTTPException(status_code=409, detail=f"Agent '{req.id}' already exists")

    data = {
        "id": req.id,
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

    ConfigLoader.load()
    register_generic_agents()  # so it's dispatchable (pingable, runnable) immediately
    return {"status": "created", "agent_id": req.id, "path": str(dest)}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    """Refuses to delete built-in agents (the rest of the system assumes
    they exist). Factory-created agents are always deletable, even though
    they now have a real (generic) handler too -- see registry.py."""
    agent = ConfigLoader.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    if agent_id in BUILTIN_AGENT_IDS:
        raise HTTPException(
            status_code=409,
            detail=f"'{agent_id}' is a built-in agent -- it can't be deleted.",
        )

    dest = _validated_dest(agent_id)
    if not dest.exists():
        raise HTTPException(status_code=404, detail=f"No config file for '{agent_id}'")

    dest.unlink()
    ConfigLoader.load()
    bus.unregister_handler(agent_id)
    return {"status": "deleted", "agent_id": agent_id}
