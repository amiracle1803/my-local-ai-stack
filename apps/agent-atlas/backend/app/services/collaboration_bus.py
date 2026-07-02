"""
collaboration_bus.py  --  In-process pub/sub between agents.

No decorators, no middleware: agents register a handler under their
agent_id (done once at startup, see agents/registry.py) and anything can
route a message to them by id via send_message(). This is intentionally
the simplest thing that works -- a module-level dict -- rather than a
framework, since everything runs in one process.

Every dispatched message is persisted (payload capped at 4KB so a large
tool result can't bloat the messages table) and broadcast to a listener
set by set_broadcast_hook() -- the WebSocket bus (Phase 4) registers
itself there so the frontend can show live agent activity. Until
something registers a hook, broadcasting is a no-op, so this module has
no dependency on WS existing.
"""

import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from app.models.message import AgentMessage
from app.storage.database import get_connection

logger = logging.getLogger("agent_atlas.bus")

Handler = Callable[[AgentMessage], Awaitable[Any]]
BroadcastHook = Callable[[Dict[str, Any]], Awaitable[None]]

_handlers: Dict[str, Handler] = {}
_broadcast_hook: Optional[BroadcastHook] = None

_MAX_PAYLOAD_BYTES = 4096


class NoHandlerError(LookupError):
    """Raised when dispatching to an agent_id with no registered handler.
    Plain LookupError subclass (not KeyError) so str(exc) gives a clean
    message -- KeyError's __str__ wraps the message in an extra repr()."""


def register_handler(agent_id: str, handler: Handler) -> None:
    _handlers[agent_id] = handler


def has_handler(agent_id: str) -> bool:
    return agent_id in _handlers


def list_handlers() -> list[str]:
    return sorted(_handlers.keys())


def set_broadcast_hook(hook: Optional[BroadcastHook]) -> None:
    global _broadcast_hook
    _broadcast_hook = hook


def _truncated_payload_json(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, default=str)
    if len(raw.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        return json.dumps({"_truncated": True, "preview": raw[:500]})
    return raw


def _persist(msg: AgentMessage) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO messages
               (id, conversation_id, room_id, from_agent, to_agent, role, type,
                payload_json, job_id, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (msg.message_id, msg.conversation_id, msg.room_id, msg.from_agent,
             msg.to_agent, msg.role, msg.type, _truncated_payload_json(msg.payload),
             msg.job_id, msg.created_at),
        )
        conn.commit()
    finally:
        conn.close()


async def dispatch_message(msg: AgentMessage) -> Any:
    """Look up the handler for msg.to_agent and call it. Raises KeyError if
    no handler is registered -- callers that want a soft failure should
    check has_handler() first."""
    handler = _handlers.get(msg.to_agent)
    if handler is None:
        raise NoHandlerError(f"no handler registered for agent '{msg.to_agent}'")

    _persist(msg)
    if _broadcast_hook is not None:
        task_preview = str(msg.payload.get("goal") or msg.payload.get("task") or "")[:120]
        await _broadcast_hook({
            "event": "agent_message",
            "from_agent": msg.from_agent,
            "to_agent": msg.to_agent,
            "type": msg.type,
            "conversation_id": msg.conversation_id,
            "job_id": msg.job_id,
            "task": task_preview,
        })

    logger.debug("dispatch %s -> %s (%s)", msg.from_agent, msg.to_agent, msg.type)
    return await handler(msg)


async def send_message(
    from_agent: str,
    to_agent: str,
    msg_type: str,
    payload: Dict[str, Any],
    conversation_id: Optional[str] = None,
    room_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Any:
    msg = AgentMessage(
        from_agent=from_agent,
        to_agent=to_agent,
        type=msg_type,
        payload=payload,
        conversation_id=conversation_id,
        room_id=room_id,
        job_id=job_id,
    )
    return await dispatch_message(msg)
