"""
mcp_client.py  --  Call tools from Docker Desktop's MCP Toolkit gateway.

Rather than reimplementing web search, GitHub, n8n, etc. by hand (the old
Agent Atlas's approach -- a crude DuckDuckGo scraper, a bespoke
n8n_client.py), this calls out to the gateway's already-cataloged
servers instead. See docker mcp catalog show / profile server ls.

The gateway exposes a small set of meta-tools rather than every catalog
tool flatly: mcp-add({"name": server}) brings a server's tools into scope
for this session, then mcp-exec({"name": tool, "arguments": {...}}) calls
one. call_tool() below wraps that two-step dance behind a single call.

The gateway is a prerequisite service, not something Agent Atlas starts
itself (same category as Ollama/n8n) -- see foundation/start-mcp-gateway.bat
and start.bat's health check. If it's not running, or the target server
needs a secret that hasn't been configured yet (docker mcp secret set
<server>.<key>=<value>), call_tool() raises McpGatewayError with a message
that says exactly which is true -- both are legitimate, expected states
for a fresh setup, not bugs.
"""

import logging
import os
from typing import Any, Dict

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger("agent_atlas.mcp_client")

GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://127.0.0.1:8811/sse")
GATEWAY_TOKEN = os.getenv("MCP_GATEWAY_AUTH_TOKEN", "agent-atlas-dev-fixed-token-12345")
_TIMEOUT_S = 30.0

# Servers mcp-add'ed successfully already this process's lifetime, so
# repeat calls to the same server skip straight to mcp-exec.
_activated: set[str] = set()


class McpGatewayError(RuntimeError):
    pass


def _result_text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


async def call_tool(server: str, tool: str, arguments: Dict[str, Any]) -> str:
    # error_msg is set (not raised) inside the async-with blocks and raised
    # only after they've torn down cleanly. Raising McpGatewayError while
    # still inside sse_client/ClientSession's context managers lets
    # anyio's TaskGroup wrap it in an ExceptionGroup during shutdown, which
    # then falls through the `except McpGatewayError` clause below (it's a
    # different type) and gets misreported as a connection failure instead
    # of the real, more specific error.
    error_msg: str | None = None
    text = ""
    try:
        headers = {"Authorization": f"Bearer {GATEWAY_TOKEN}"}
        async with sse_client(GATEWAY_URL, headers=headers, timeout=_TIMEOUT_S) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                if server not in _activated:
                    add_result = await session.call_tool("mcp-add", {"name": server})
                    text = _result_text(add_result)
                    if getattr(add_result, "isError", False) or "Missing required secrets" in text:
                        error_msg = f"'{server}' isn't usable yet -- {text.strip() or 'missing configuration'}"
                    else:
                        _activated.add(server)

                if error_msg is None:
                    result = await session.call_tool("mcp-exec", {"name": tool, "arguments": arguments})
                    text = _result_text(result)
                    if getattr(result, "isError", False):
                        error_msg = f"{tool} failed: {text}"
    except Exception as exc:  # noqa: BLE001
        raise McpGatewayError(
            f"Couldn't reach the MCP gateway at {GATEWAY_URL} -- is it running? "
            f"(foundation/start-mcp-gateway.bat) [{type(exc).__name__}: {exc}]"
        ) from exc

    if error_msg is not None:
        raise McpGatewayError(error_msg)
    return text


async def find_servers(query: str, limit: int = 10) -> str:
    """Search the full Docker MCP catalog (315+ servers) by keyword --
    useful for discovering what's available beyond the amir_ai_agents
    profile's 7 pre-enabled servers."""
    try:
        headers = {"Authorization": f"Bearer {GATEWAY_TOKEN}"}
        async with sse_client(GATEWAY_URL, headers=headers, timeout=_TIMEOUT_S) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("mcp-find", {"query": query, "limit": limit})
                return _result_text(result)
    except Exception as exc:  # noqa: BLE001
        raise McpGatewayError(
            f"Couldn't reach the MCP gateway at {GATEWAY_URL} -- is it running? "
            f"[{type(exc).__name__}: {exc}]"
        ) from exc
