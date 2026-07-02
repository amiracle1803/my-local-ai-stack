import json
import logging
from typing import Any, Callable, Dict, Optional

from app.models.message import AgentMessage, MessageMetadata
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.bus")

# Agent handler registry: agent_id → async callable(AgentMessage) → Any
_handlers: Dict[str, Callable] = {}


def register_handler(agent_id: str, handler: Callable):
    _handlers[agent_id] = handler
    logger.debug("Registered handler for agent '%s'", agent_id)


def has_handler(agent_id: str) -> bool:
    return agent_id in _handlers


def list_handlers() -> list[str]:
    return sorted(_handlers.keys())


def build_message(
    from_agent: str,
    to_agent: str,
    msg_type: str,
    payload: Dict[str, Any],
    role: str = "request",
    conversation_id: Optional[str] = None,
    room_id: Optional[str] = None,
    priority: str = "normal",
    runtime_mode: str = "sync",
    user_visible: bool = False,
) -> AgentMessage:
    return AgentMessage(
        message_id=new_id(),
        conversation_id=conversation_id or new_id(),
        room_id=room_id,
        from_agent=from_agent,
        to_agent=to_agent,
        role=role,
        type=msg_type,
        payload=payload,
        created_at=now_iso(),
        metadata=MessageMetadata(
            priority=priority,
            runtime_mode=runtime_mode,
            user_visible=user_visible,
        ),
    )


_PERSIST_MAX_BYTES = 4096  # cap stored payload so messages table doesn't bloat


def _persist(msg: AgentMessage):
    conn = None
    try:
        conn = get_connection()
        payload_json = json.dumps(msg.payload)
        if len(payload_json) > _PERSIST_MAX_BYTES:
            payload_json = json.dumps({
                "_truncated": True,
                "goal": str(msg.payload.get("goal", msg.payload.get("task", msg.payload.get("query", ""))))[:400],
                "size_bytes": len(payload_json),
            })
        conn.execute(
            """INSERT OR IGNORE INTO messages
               (id, room_id, conversation_id, from_agent, to_agent, role, type, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg.message_id,
                msg.room_id,
                msg.conversation_id,
                msg.from_agent,
                msg.to_agent,
                msg.role,
                msg.type,
                payload_json,
                msg.created_at,
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Failed to persist message %s: %s", msg.message_id, exc)
    finally:
        if conn:
            conn.close()


async def dispatch_message(msg: AgentMessage) -> Optional[Any]:
    _persist(msg)
    handler = _handlers.get(msg.to_agent)
    if not handler:
        raise ValueError(
            f"No handler registered for agent '{msg.to_agent}'. "
            f"Available: {list(_handlers.keys())}"
        )
    logger.debug("Dispatching %s → %s [%s]", msg.from_agent, msg.to_agent, msg.type)

    # Broadcast every inter-agent message so the frontend can show live activity
    try:
        import asyncio
        from app.services import ws_bus
        # Include a short task snippet so the UI can show what each agent is doing
        task_snippet = (
            msg.payload.get("task")
            or msg.payload.get("goal")
            or msg.payload.get("query")
            or ""
        )
        asyncio.create_task(ws_bus.broadcast({
            "event": "agent_message",
            "from": msg.from_agent,
            "to": msg.to_agent,
            "type": msg.type,
            "conversation_id": msg.conversation_id,
            "job_id": msg.payload.get("_job_id"),
            "task": str(task_snippet)[:160] if task_snippet else None,
        }))
    except Exception:
        pass

    return await handler(msg)


async def send_message(
    from_agent: str,
    to_agent: str,
    msg_type: str,
    payload: Dict[str, Any],
    **kwargs,
) -> Optional[Any]:
    msg = build_message(from_agent, to_agent, msg_type, payload, **kwargs)
    return await dispatch_message(msg)
