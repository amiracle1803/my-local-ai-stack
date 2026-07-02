"""
WebSocket endpoint — /ws
Clients receive real-time events: job_update, agent_message, system_event.
"""
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import ws_bus

logger = logging.getLogger("agent_atlas.api.ws")
router = APIRouter()

_RECEIVE_TIMEOUT = 60.0   # seconds to wait for a client frame before sending a server ping
_PING_TIMEOUT    = 10.0   # seconds the client has to respond to the server ping


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    accepted = await ws_bus.connect(websocket)
    if not accepted:
        return  # connect() already closed the socket with 1008
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=_RECEIVE_TIMEOUT)
            except asyncio.TimeoutError:
                # No frame received — send a keepalive ping to detect dead connections
                try:
                    await asyncio.wait_for(
                        websocket.send_text('{"event":"ping"}'),
                        timeout=_PING_TIMEOUT,
                    )
                except Exception:
                    # Cannot write to socket — treat as disconnected
                    break
                continue

            if data == "ping":
                await websocket.send_text('{"event":"pong"}')
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS error: %s", exc)
    finally:
        ws_bus.disconnect(websocket)
