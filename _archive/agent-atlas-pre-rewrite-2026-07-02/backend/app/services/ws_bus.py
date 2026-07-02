"""
Lightweight WebSocket broadcast bus.
All connected clients receive every event (job updates, agent messages, etc.).
"""
import json
import logging
from typing import Any, Dict, Set

from fastapi import WebSocket

logger = logging.getLogger("agent_atlas.ws_bus")

_connections: Set[WebSocket] = set()
_MAX_WS_CONNECTIONS = 50  # soft cap — rejects new connections when exceeded


async def connect(ws: WebSocket) -> bool:
    """Accept a WebSocket connection. Returns False (and closes) if the cap is hit."""
    if len(_connections) >= _MAX_WS_CONNECTIONS:
        await ws.close(code=1008, reason="Connection limit reached")
        logger.warning("WS connection rejected — cap of %d reached", _MAX_WS_CONNECTIONS)
        return False
    await ws.accept()
    _connections.add(ws)
    logger.debug("WS client connected (%d total)", len(_connections))
    return True


def disconnect(ws: WebSocket):
    _connections.discard(ws)
    logger.debug("WS client disconnected (%d remaining)", len(_connections))


async def broadcast(data: Dict[str, Any]):
    if not _connections:
        return
    msg = json.dumps(data)
    dead = set()
    for ws in list(_connections):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    for ws in dead:
        _connections.discard(ws)
