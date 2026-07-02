import asyncio
import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.services import collaboration_bus as bus

logger = logging.getLogger("agent_atlas.agents.knowledge_hub")


class KnowledgeHubAgent(BaseAgent):
    agent_id = "knowledge_hub"

    async def handle(self, message: AgentMessage) -> Any:
        query = (
            message.payload.get("query")
            or message.payload.get("task")
            or message.payload.get("goal")
            or ""
        )
        context  = message.payload.get("context", {})
        _job_id  = message.payload.get("_job_id") or context.get("_job_id")
        logger.info("[knowledge_hub] query: %s", query[:80])

        # Fan-out: vector retrieval + Obsidian search in parallel
        retrieval_coro = bus.send_message(
            from_agent="knowledge_hub",
            to_agent="retrieval_agent",
            msg_type="retrieve_request",
            payload={"query": query, "_job_id": _job_id, "context": context},
            conversation_id=message.conversation_id,
        )
        obsidian_coro = bus.send_message(
            from_agent="knowledge_hub",
            to_agent="obsidian_brain",
            msg_type="search",
            payload={"query": query, "_job_id": _job_id, "context": context},
            conversation_id=message.conversation_id,
        )

        local_result, obsidian_result = await asyncio.gather(
            retrieval_coro, obsidian_coro, return_exceptions=True
        )

        def _safe(r: Any) -> Any:
            return {"error": str(r)} if isinstance(r, Exception) else r

        evidence = {
            "local": _safe(local_result),
            "obsidian": _safe(obsidian_result),
        }

        # Synthesize evidence into a readable answer using context awareness
        preamble = self._build_context_preamble(context)
        evidence_text = json.dumps(evidence, default=str)[:2000]
        synthesis_prompt = (
            f"{preamble}"
            f"You retrieved the following evidence for the query: '{query}'\n\n"
            f"{evidence_text}\n\n"
            f"Summarize the key findings in a clear, concise paragraph. "
            f"If the evidence is empty or irrelevant, say so and answer from your own knowledge."
        )
        try:
            summary = await self.llm_call(synthesis_prompt)
        except Exception as exc:
            logger.warning("[knowledge_hub] synthesis LLM failed: %s", exc)
            summary = evidence_text

        logger.info("[knowledge_hub] gathered 2 sources, synthesized answer")
        return {"response": summary, "evidence": evidence, "query": query}
