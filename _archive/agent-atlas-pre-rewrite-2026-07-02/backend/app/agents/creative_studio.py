import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage

logger = logging.getLogger("agent_atlas.agents.creative_studio")

CREATIVE_PROMPT = """{preamble}You are a skilled writer and documentation expert.

Request: {subject}

Write the requested content. Be clear, well-structured, and appropriately detailed. Use markdown for formatting when it improves readability."""


class CreativeStudioAgent(BaseAgent):
    agent_id = "creative_studio_agent"

    async def handle(self, message: AgentMessage) -> Any:
        context = message.payload.get("context", {})

        # Accept subtask format (task/goal) OR direct call format (subject/doc_type)
        subject = (
            message.payload.get("subject")
            or message.payload.get("task")
            or message.payload.get("goal")
            or message.payload.get("description")
            or ""
        )
        doc_type = message.payload.get("doc_type", "content")
        logger.info("[creative_studio] Creating %s: %s", doc_type, subject[:60])

        preamble = self._build_context_preamble(context)
        result = await self.llm_call(
            CREATIVE_PROMPT.format(preamble=preamble, subject=subject)
        )
        return {"content": result, "doc_type": doc_type, "subject": subject}
