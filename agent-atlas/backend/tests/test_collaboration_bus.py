"""Tests for the Collaboration Bus routing and persistence."""
import pytest

from app.services import collaboration_bus as bus
from app.models.message import AgentMessage


@pytest.fixture(autouse=True)
def clear_handlers():
    bus._handlers.clear()
    yield
    bus._handlers.clear()


def test_register_and_dispatch():
    received = []

    async def my_handler(msg: AgentMessage):
        received.append(msg.payload)
        return {"ok": True}

    bus.register_handler("test_agent", my_handler)

    import asyncio
    msg = bus.build_message("sender", "test_agent", "ping", {"data": 42})
    result = asyncio.run(bus.dispatch_message(msg))

    assert result == {"ok": True}
    assert received == [{"data": 42}]


def test_dispatch_unknown_agent_raises():
    import asyncio
    msg = bus.build_message("a", "ghost_agent", "ping", {})
    with pytest.raises(ValueError, match="No handler registered"):
        asyncio.run(bus.dispatch_message(msg))


def test_message_persisted_to_db():
    from app.storage.database import get_connection

    async def noop(msg):
        return None

    bus.register_handler("persist_target", noop)
    msg = bus.build_message("src", "persist_target", "test_event", {"key": "val"})

    import asyncio
    asyncio.run(bus.dispatch_message(msg))

    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (msg.message_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["from_agent"] == "src"
    assert row["to_agent"] == "persist_target"


def test_send_message_shortcut():
    results = []

    async def echo(msg):
        results.append(msg.payload)
        return msg.payload

    bus.register_handler("echo", echo)

    import asyncio
    out = asyncio.run(
        bus.send_message("caller", "echo", "echo_req", {"hello": "world"})
    )
    assert out == {"hello": "world"}
    assert results[0] == {"hello": "world"}
