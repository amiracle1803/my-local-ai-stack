"""
base.py  --  Shared contract every agent implements.

A concrete agent subclasses BaseAgent, sets `agent_id`, and implements
`handle(message) -> Any`. Everything else (loading its own YAML config,
picking a model, retrying flaky local-model calls, tracing) is handled
here so individual agents stay focused on their actual logic.

Model routing is imported lazily inside get_model_client() rather than at
module load time -- model_router.py is added in a later build phase, and
this way base.py stays fully importable (and its retry/timeout/tracing
logic testable) before that file exists.
"""

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional

from app.config.loader import ConfigLoader
from app.models.agent import AgentDefinition
from app.models.message import AgentMessage

logger = logging.getLogger("agent_atlas.agents")

# Shared across all agents: LM Studio in particular misbehaves under
# concurrent requests, so cap how many llm_call()s run at once regardless
# of which agent issued them.
_LLM_SEMAPHORE = asyncio.Semaphore(2)
_LLM_TIMEOUT_S = 60.0
_LLM_RETRIES = 3

# Set by Phase 4's Langfuse integration; no-op until then. Signature:
# (agent_id, duration_ms, success, input_preview, output_preview) -> None
TraceHook = Callable[[str, float, bool, str, str], None]
_trace_hook: Optional[TraceHook] = None


def set_trace_hook(hook: Optional[TraceHook]) -> None:
    global _trace_hook
    _trace_hook = hook


class BaseAgent:
    agent_id: str = ""

    def __init__(self) -> None:
        if not self.agent_id:
            raise ValueError(f"{type(self).__name__} must set agent_id")
        raw = ConfigLoader.get_agent(self.agent_id)
        if raw is None:
            raise ValueError(
                f"No config/agents/{self.agent_id}.yml found for agent '{self.agent_id}'"
            )
        self.definition = AgentDefinition(**raw)

    async def handle(self, message: AgentMessage) -> Any:
        raise NotImplementedError(f"{type(self).__name__} must implement handle()")

    async def handle_traced(self, message: AgentMessage) -> Any:
        start = time.monotonic()
        success = True
        try:
            result = await self.handle(message)
            return result
        except Exception:
            success = False
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            if _trace_hook is not None:
                try:
                    _trace_hook(
                        self.agent_id, duration_ms, success,
                        str(message.payload)[:500], "",
                    )
                except Exception:  # noqa: BLE001 - tracing must never break the call
                    logger.exception("trace hook failed for %s", self.agent_id)
            logger.info("%s handled %s in %.0fms (success=%s)",
                        self.agent_id, message.type, duration_ms, success)

    def get_model_client(self):
        from app.services.model_router import get_best_client  # lazy: added in Phase 2
        return get_best_client(preferred=self.definition.model_preference)

    async def llm_call(self, user_prompt: str, system: Optional[str] = None, **kwargs) -> str:
        last_exc: Optional[Exception] = None
        for attempt in range(1, _LLM_RETRIES + 1):
            try:
                async with _LLM_SEMAPHORE:
                    client = self.get_model_client()
                    messages = []
                    if system:
                        messages.append({"role": "system", "content": system})
                    messages.append({"role": "user", "content": user_prompt})
                    response = await asyncio.wait_for(
                        client.chat(messages, **kwargs), timeout=_LLM_TIMEOUT_S,
                    )
                return response["content"] if isinstance(response, dict) else str(response)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < _LLM_RETRIES:
                    await asyncio.sleep(0.5 * attempt)
        raise RuntimeError(f"llm_call failed after {_LLM_RETRIES} attempts: {last_exc}") from last_exc

    def build_context_preamble(self, context: dict) -> str:
        """Format prior conversation/memory/results into a text block a
        prompt can prepend. Agents call this themselves where relevant --
        not every agent needs conversation history."""
        if not context:
            return ""
        parts = []
        if history := context.get("history"):
            parts.append("Prior turns:\n" + "\n".join(f"- {h}" for h in history))
        if memory := context.get("memory"):
            parts.append("Relevant memory:\n" + "\n".join(f"- {m}" for m in memory))
        if prior_result := context.get("prior_result"):
            parts.append(f"Previous result:\n{prior_result}")
        return "\n\n".join(parts)
