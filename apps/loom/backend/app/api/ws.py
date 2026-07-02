import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import ws_bus

logger = logging.getLogger("agent_atlas.api.ws")
router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    accepted = await ws_bus.connect(websocket)
    if not accepted:
        await websocket.close(code=1008, reason="too many connections")
        return
    try:
        while True:
            # Clients don't send anything meaningful -- this is a pure
            # broadcast channel. Just wait for disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.debug("ws connection ended unexpectedly", exc_info=True)
    finally:
        await ws_bus.disconnect(websocket)
