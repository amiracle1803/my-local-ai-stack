"""
n8n_client.py  --  Talk to the n8n instance this stack already runs.

Reuses foundation/.env's N8N_API_KEY -- the same key
apps/project1-ops-hub/app.py already reads to show workflow counts on
the dashboard's Integrations page -- rather than configuring a second,
redundant n8n credential through the Docker MCP gateway's n8n server.

Read-only + additive only (list, get, create). Deliberately does not
implement "run workflow": this n8n instance has a live "ai checking
emails" workflow, and triggering workflow execution needs to know each
workflow's specific trigger type (webhook URL, schedule, manual) to do
safely -- guessing at that risked real side effects during development.
Add it once there's a concrete, verified need.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("agent_atlas.n8n_client")

N8N_URL = "http://localhost:5678"
_ENV_FILE = Path(__file__).parent.parent.parent.parent.parent.parent / "foundation" / ".env"


def _api_key() -> Optional[str]:
    if not _ENV_FILE.exists():
        return None
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("N8N_API_KEY="):
            value = line.split("=", 1)[1].strip()
            return value or None
    return None


class N8nUnavailableError(RuntimeError):
    pass


async def list_workflows() -> List[Dict[str, Any]]:
    key = _api_key()
    if not key:
        raise N8nUnavailableError("N8N_API_KEY not set in foundation/.env")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{N8N_URL}/api/v1/workflows", headers={"X-N8N-API-KEY": key})
        resp.raise_for_status()
        return resp.json().get("data", [])


async def get_workflow(workflow_id: str) -> Dict[str, Any]:
    key = _api_key()
    if not key:
        raise N8nUnavailableError("N8N_API_KEY not set in foundation/.env")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{N8N_URL}/api/v1/workflows/{workflow_id}", headers={"X-N8N-API-KEY": key})
        resp.raise_for_status()
        return resp.json()


async def create_workflow(name: str, nodes: List[Dict[str, Any]], connections: Dict[str, Any]) -> Dict[str, Any]:
    key = _api_key()
    if not key:
        raise N8nUnavailableError("N8N_API_KEY not set in foundation/.env")
    body = {"name": name, "nodes": nodes, "connections": connections, "settings": {}}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{N8N_URL}/api/v1/workflows", json=body, headers={"X-N8N-API-KEY": key})
        resp.raise_for_status()
        return resp.json()
