"""
n8n_client.py -- thin async wrapper around n8n's REST API (v1).

Lets agents create, activate, and run n8n workflows programmatically instead
of only through n8n's own web UI. Used by AutomationAgent (natural-language
"build me a workflow that..." requests) and exposed directly as MCP tools
in api/mcp_server.py for any MCP client (Claude Desktop, OpenCode, etc).

Key facts about this n8n instance that shape the design below:
  - It's the SAME n8n the my-local-ai-stack Flask dashboard already talks to
    (docker-compose, foundation/.env). We read N8N_API_KEY from that same
    .env file so there's one key, not a duplicate to keep in sync.
  - n8n's public REST API has no "run workflow by id" endpoint (confirmed:
    POST /workflows/{id}/run -> 405). The only way to trigger a workflow
    over HTTP is a Webhook trigger node's own URL. So workflows this client
    creates for agents to test/run should use a Webhook trigger, not a
    Manual Trigger (Manual Trigger only runs from the n8n editor UI).
  - n8n runs in Docker. From inside its container, "localhost" is the
    container itself -- to reach Ollama on the host, nodes must call
    http://host.docker.internal:11434, not http://localhost:11434.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import httpx

_DEFAULT_BASE_URL = "http://localhost:5678"


def _base_url() -> str:
    return os.getenv("N8N_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> Optional[str]:
    """N8N_API_KEY from this process's env, falling back to the dashboard's
    foundation/.env so both apps share one key the user pastes once."""
    env_key = os.getenv("N8N_API_KEY", "").strip()
    if env_key:
        return env_key
    # backend/app/services/n8n_client.py -> parents[4] == my-local-ai-stack/
    env_file = Path(__file__).resolve().parents[4] / "foundation" / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("N8N_API_KEY="):
            value = line.split("=", 1)[1].strip()
            return value or None
    return None


class N8nError(RuntimeError):
    pass


def _headers() -> dict:
    key = _api_key()
    if not key:
        raise N8nError(
            "No N8N_API_KEY configured. Generate one in n8n (Settings -> n8n API "
            "-> Create an API key) and paste it into foundation/.env."
        )
    return {"X-N8N-API-KEY": key, "Content-Type": "application/json"}


async def _request(method: str, path: str, **kwargs) -> Any:
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.request(method, url, headers=_headers(), **kwargs)
    except httpx.RequestError as exc:
        raise N8nError(f"Could not reach n8n at {_base_url()}: {exc}") from exc
    if resp.status_code >= 400:
        raise N8nError(f"n8n API {method} {path} -> {resp.status_code}: {resp.text[:400]}")
    if not resp.content:
        return None
    return resp.json()


# ── read ──────────────────────────────────────────────────────────────────

async def list_workflows() -> list[dict]:
    data = await _request("GET", "/api/v1/workflows")
    return data.get("data", []) if data else []


async def get_workflow(workflow_id: str) -> dict:
    return await _request("GET", f"/api/v1/workflows/{workflow_id}")


async def list_executions(workflow_id: Optional[str] = None, limit: int = 10) -> list[dict]:
    params = {"limit": max(1, min(50, limit))}
    if workflow_id:
        params["workflowId"] = workflow_id
    data = await _request("GET", "/api/v1/executions", params=params)
    return data.get("data", []) if data else []


async def get_execution(execution_id: str) -> dict:
    return await _request("GET", f"/api/v1/executions/{execution_id}")


# ── write ─────────────────────────────────────────────────────────────────

def _normalize_connections(connections: dict) -> dict:
    """
    Repairs the most common shapes a small local LLM gets wrong when it
    drafts n8n `connections` JSON:
      - a single target dict instead of a list of targets
      - a flat list of targets instead of a list of output-groups
      - missing "type"/"index" on a target
    n8n's real shape is: {source: {"main": [ [ {node, type, index}, ... ] ]}}
    (outer list = one entry per output pin, inner list = targets on that pin).
    Already-correct input passes through unchanged.
    """
    normalized: dict = {}
    for src, outputs in (connections or {}).items():
        if not isinstance(outputs, dict):
            continue
        norm_outputs = {}
        for conn_type, value in outputs.items():
            if isinstance(value, dict):
                value = [value]
            if isinstance(value, list) and value and isinstance(value[0], dict):
                value = [value]  # flat list of targets -> single output-group
            groups = []
            for group in value or []:
                if isinstance(group, dict):
                    group = [group]
                targets = [
                    {"node": t["node"], "type": t.get("type", "main"), "index": t.get("index", 0)}
                    for t in group if isinstance(t, dict) and "node" in t
                ]
                groups.append(targets)
            norm_outputs[conn_type] = groups
        normalized[src] = norm_outputs
    return normalized


def _normalize_http_request_nodes(nodes: list[dict]) -> list[dict]:
    """
    A small local LLM reliably drafts *some* JSON body for an HTTP Request
    node (usually to call Ollama) but its exact parameter shape varies by
    n8n's httpRequest typeVersion and is easy to get wrong (e.g. missing
    "sendBody", using an old "bodyType"/"body" shape instead of
    "specifyBody"/"jsonBody"). Coerce any httpRequest node that clearly
    intends a JSON body onto the known-working v4.4 shape rather than
    trying to validate every possible variant.
    """
    for node in nodes:
        if node.get("type") != "n8n-nodes-base.httpRequest":
            continue
        params = node.get("parameters", {}) or {}
        raw_body = params.get("jsonBody") or params.get("body")
        if raw_body is None:
            continue  # no JSON body intended (e.g. a plain GET) -- leave as-is
        if isinstance(raw_body, dict):
            raw_body = json.dumps(raw_body)
        already_correct = params.get("sendBody") and params.get("specifyBody") == "json"
        if already_correct:
            continue
        node["parameters"] = {
            "method": params.get("method", "POST"),
            "url": params.get("url", ""),
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": raw_body,
            "options": {},
        }
        node["typeVersion"] = 4.4
    return nodes


async def create_workflow(
    name: str,
    nodes: list[dict],
    connections: dict,
    settings: Optional[dict] = None,
    activate: bool = False,
) -> dict:
    body = {
        "name": name,
        "nodes": _normalize_http_request_nodes(nodes),
        "connections": _normalize_connections(connections),
        "settings": settings or {"executionOrder": "v1"},
    }
    created = await _request("POST", "/api/v1/workflows", json=body)
    if activate and created and created.get("id"):
        await set_active(created["id"], True)
        created["active"] = True
    return created


async def update_workflow(workflow_id: str, **fields) -> dict:
    return await _request("PATCH", f"/api/v1/workflows/{workflow_id}", json=fields)


async def set_active(workflow_id: str, active: bool) -> dict:
    suffix = "activate" if active else "deactivate"
    return await _request("POST", f"/api/v1/workflows/{workflow_id}/{suffix}")


async def delete_workflow(workflow_id: str) -> dict:
    return await _request("DELETE", f"/api/v1/workflows/{workflow_id}")


# ── running a workflow (webhook trigger only -- see module docstring) ──────

def find_webhook_path(workflow: dict) -> Optional[str]:
    """Return the first Webhook trigger node's path, if the workflow has one."""
    for node in workflow.get("nodes", []):
        if node.get("type") == "n8n-nodes-base.webhook":
            path = node.get("parameters", {}).get("path")
            if path:
                return path
    return None


async def run_via_webhook(path: str, payload: Optional[dict] = None, test_mode: bool = False) -> dict:
    """
    Trigger a workflow through its Webhook node.
    test_mode=True hits /webhook-test/<path> (only works while the workflow
    is open + "listening" in the n8n editor); normal mode hits /webhook/<path>
    which requires the workflow to be active.
    """
    prefix = "webhook-test" if test_mode else "webhook"
    url = f"{_base_url()}/{prefix}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload or {})
    except httpx.RequestError as exc:
        raise N8nError(f"Could not reach webhook {url}: {exc}") from exc
    body: Any
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = resp.text[:2000]
    return {"status_code": resp.status_code, "body": body}


# ── node-building helpers (optional convenience, not required) ─────────────

def webhook_trigger_node(path: str, name: str = "Webhook") -> dict:
    return {
        "parameters": {"path": path, "httpMethod": "POST", "responseMode": "lastNode"},
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 0],
        "name": name,
    }


def schedule_trigger_node(cron_expression: str, name: str = "Schedule Trigger") -> dict:
    return {
        "parameters": {
            "rule": {"interval": [{"field": "cronExpression", "expression": cron_expression}]}
        },
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "position": [0, 0],
        "name": name,
    }


def ollama_http_request_node(model: str, prompt: str, name: str = "Ask Ollama") -> dict:
    """HTTP Request node calling the local Ollama server. Must use
    host.docker.internal, not localhost -- n8n runs inside Docker."""
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False})
    return {
        "parameters": {
            "method": "POST",
            "url": "http://host.docker.internal:11434/v1/chat/completions",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": body,
            "options": {},
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.4,
        "position": [220, 0],
        "name": name,
    }


def chain(*node_names: str) -> dict:
    """Build a simple linear `connections` block: node[0] -> node[1] -> ..."""
    conns: dict = {}
    for a, b in zip(node_names, node_names[1:]):
        conns[a] = {"main": [[{"node": b, "type": "main", "index": 0}]]}
    return conns
