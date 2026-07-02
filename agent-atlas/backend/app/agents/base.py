import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from app.config.loader import ConfigLoader
from app.models.agent import AgentDefinition
from app.models.message import AgentMessage
from app.services.llm_clients import ModelClient, build_client
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.agents")

# Cap concurrent LLM calls so LM Studio doesn't get overwhelmed.
# Lazy init — Semaphore must be created inside the running event loop.
_LLM_SEMAPHORE: Optional[asyncio.Semaphore] = None
_LLM_MAX_CONCURRENT = 2          # LM Studio is single-threaded; 2 is safe for both Ollama and LM Studio
_LLM_TIMEOUT_SECONDS = 60        # per-call hard timeout (LM Studio can be slow to start generating)


def _get_llm_semaphore() -> asyncio.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        _LLM_SEMAPHORE = asyncio.Semaphore(_LLM_MAX_CONCURRENT)
    return _LLM_SEMAPHORE


class BaseAgent(ABC):
    agent_id: str = "base"

    def __init__(self):
        raw = ConfigLoader.get_agent(self.agent_id) or {}
        self.definition = AgentDefinition(
            id=raw.get("id", self.agent_id),
            display_name=raw.get("display_name", self.agent_id),
            layer=raw.get("layer", "control"),
            description=raw.get("description", ""),
            inputs=raw.get("inputs", []),
            outputs=raw.get("outputs", []),
            tools=raw.get("tools", []),
            model_preference=raw.get("model_preference", ["hermes_local"]),
            memory_scopes=raw.get("memory_scopes", []),
            policies=raw.get("policies", []),
            system_prompt=raw.get("system_prompt"),
        )
        self._active_model: Optional[str] = None

    def get_model_client(self) -> Optional[ModelClient]:
        for model_name in self.definition.model_preference:
            client = build_client(model_name)
            if client:
                self._active_model = model_name
                return client
        return None

    @staticmethod
    def _build_context_preamble(context: dict) -> str:
        """Return a text block to prepend to prompts so agents are aware of conversation state."""
        parts = []

        if context.get("is_followup"):
            prev_goal   = context.get("previous_goal", "")
            prev_result = context.get("previous_result", "")
            turn        = context.get("conversation_turn", "")
            header = f"[FOLLOW-UP CONVERSATION — Turn {turn}]" if turn else "[FOLLOW-UP CONVERSATION]"
            block = header
            if prev_goal:
                block += f"\nPrevious task: {prev_goal}"
            if prev_result:
                block += f"\nPrevious result summary:\n{prev_result[:900]}"
            history = context.get("conversation_history", [])
            if len(history) > 1:
                lines = "\n".join(
                    f"  Turn {i+1}: {t.get('goal','')} → {str(t.get('result',''))[:200]}"
                    for i, t in enumerate(history[:-1])
                )
                block += f"\nFull conversation history:\n{lines}"
            parts.append(block)

        if context.get("memory_context"):
            parts.append(context["memory_context"])

        if context.get("prior_results"):
            snippets = "\n".join(
                f"  [{k}] {str(v)[:250]}"
                for k, v in context["prior_results"].items()
            )
            parts.append(f"[PRIOR SUBTASK RESULTS]\n{snippets}")

        if not parts:
            return ""
        return "\n\n".join(parts) + "\n\n---\n\n"

    async def llm_call(self, user_prompt: str, system: Optional[str] = None, **kwargs) -> str:
        from app.services.model_router import get_best_client, invalidate_cache
        messages = []
        if system or self.definition.system_prompt:
            messages.append({"role": "system", "content": system or self.definition.system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # Retry up to 3 times — each failure invalidates the chosen model so
        # the router falls through to the next available option automatically.
        last_exc: Exception = RuntimeError("No LLM available")
        for attempt in range(3):
            try:
                client = await get_best_client(self.definition.model_preference or None)
                async with _get_llm_semaphore():
                    result = await asyncio.wait_for(
                        client.chat(messages, **kwargs),
                        timeout=_LLM_TIMEOUT_SECONDS,
                    )
                return result["content"]
            except asyncio.TimeoutError:
                last_exc = RuntimeError(f"LLM call timed out after {_LLM_TIMEOUT_SECONDS}s")
                invalidate_cache()
                if attempt < 2:
                    await asyncio.sleep(0.3)
            except Exception as exc:
                # Catch all exceptions (RuntimeError, httpx errors, etc.) so
                # any transient LLM failure gets retried with a fresh probe.
                last_exc = exc
                invalidate_cache()
                logger.warning("[%s] LLM attempt %d failed: %s", self.agent_id, attempt + 1, exc)
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))  # 0.5s, 1.0s backoff
        raise last_exc

    # Traces are stored in SQLite; cap the payload so conversation-history contexts
    # (which can be tens of kilobytes) don't bloat the agent_traces table.
    _TRACE_MAX_BYTES = 4096

    def _record_trace(
        self,
        message: AgentMessage,
        result: Any,
        duration_ms: float,
        success: bool = True,
    ):
        conn = None
        try:
            conn = get_connection()
            payload_json = json.dumps(message.payload, default=str)
            if len(payload_json) > self._TRACE_MAX_BYTES:
                # Keep the goal text (the useful part) and note the truncation.
                payload_json = json.dumps(
                    {
                        "_truncated": True,
                        "goal": str(message.payload.get("goal", ""))[:500],
                        "size_bytes": len(payload_json),
                    },
                    default=str,
                )
            conn.execute(
                """INSERT INTO agent_traces
                   (id, task_id, agent_id, input_json, output_json, model_used, duration_ms, success, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id(),
                    message.conversation_id,
                    self.agent_id,
                    payload_json,
                    json.dumps(result, default=str) if result is not None else None,
                    self._active_model,
                    duration_ms,
                    1 if success else 0,
                    now_iso(),
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("Failed to record trace for %s: %s", self.agent_id, exc)
        finally:
            if conn:
                conn.close()

    async def handle_traced(self, message: AgentMessage) -> Any:
        """Wraps handle() with automatic trace recording."""
        start = time.monotonic()
        success = True
        result = None
        try:
            result = await self.handle(message)
            return result
        except Exception:
            success = False
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            self._record_trace(message, result, duration_ms, success)

    @abstractmethod
    async def handle(self, message: AgentMessage) -> Any:
        ...
