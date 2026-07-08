"""
ws_bus.py  --  Broadcast agent_message/job_update events to connected
WebSocket clients (the frontend's live activity feed / busy indicators).

Registers itself as collaboration_bus's broadcast hook and
background_runtime's job_update source at startup (see main.py's
lifespan) -- neither of those modules import this one, keeping the
dependency one-directional (bus/runtime don't know WS exists; WS knows
about them).
"""

import asyncio
import json
import logging
from typing import Any, Dict, Set

from fastapi import WebSocket

logger = logging.getLogger("agent_atlas.ws_bus")

_MAX_CONNECTIONS = 50
_connections: Set[WebSocket] = set()
_lock = asyncio.Lock()


async def connect(ws: WebSocket) -> bool:
    async with _lock:
        if len(_connections) >= _MAX_CONNECTIONS:
            return False
        await ws.accept()
        _connections.add(ws)
    return True


async def disconnect(ws: WebSocket) -> None:
    async with _lock:
        _connections.discard(ws)


async def broadcast(event: Dict[str, Any]) -> None:
    if not _connections:
        return
    payload = json.dumps(event, default=str)
    dead = []
    for ws in list(_connections):
        try:
            await ws.send_text(payload)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    if dead:
        async with _lock:
            for ws in dead:
                _connections.discard(ws)
