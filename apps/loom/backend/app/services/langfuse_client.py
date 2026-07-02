"""
langfuse_client.py  --  Wire agent call tracing into Langfuse.

Self-hosted Langfuse v2 (see foundation/docker-compose-langfuse.yml),
deliberately pinned to the `langfuse==2.60.10` Python SDK -- the latest
PyPI release (4.x) speaks a v3/OTel-shaped API and fails a basic
auth_check() against a v2 server with a Pydantic validation error
(missing `organization`/`metadata` fields the v2 API doesn't return).
Verified this pin actually round-trips a trace before wiring it in here.

Optional: if Langfuse isn't running, get_client() returns None and
trace_agent_call() is a silent no-op -- exactly like search_notes()
degrading to keyword search when Ollama's embedding model is down.
Tracing must never be why an agent call fails.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("agent_atlas.langfuse")

LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://localhost:3030")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-agent-atlas-local-dev")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-agent-atlas-local-dev")

_client = None
_unavailable = False


def _get_client():
    global _client, _unavailable
    if _unavailable:
        return None
    if _client is not None:
        return _client
    try:
        from langfuse import Langfuse
        _client = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY, secret_key=LANGFUSE_SECRET_KEY, host=LANGFUSE_HOST,
        )
        return _client
    except Exception as exc:  # noqa: BLE001
        logger.info("Langfuse unavailable, tracing disabled for this run: %s", exc)
        _unavailable = True
        return None


def trace_agent_call(agent_id: str, duration_ms: float, success: bool,
                      input_preview: str, output_preview: str) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        client.trace(
            name=f"agent:{agent_id}",
            input=input_preview,
            output=output_preview,
            metadata={"duration_ms": round(duration_ms), "success": success},
            tags=["success"] if success else ["failed"],
        )
    except Exception:  # noqa: BLE001
        logger.debug("failed to send trace for %s", agent_id, exc_info=True)
