import logging
from typing import Any, Dict

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.services import collaboration_bus as bus
from app.services.mcp_client import McpGatewayError, call_tool

logger = logging.getLogger("agent_atlas.agents.knowledge_hub")


class KnowledgeHubAgent(BaseAgent):
    agent_id = "knowledge_hub"

    async def handle(self, message: AgentMessage) -> Dict[str, Any]:
        query = message.payload.get("query") or message.payload.get("goal", "")
        want_web = bool(message.payload.get("web", True))

        vault_results = []
        try:
            vault_results = await bus.send_message(
                from_agent=self.agent_id, to_agent="obsidian_brain", msg_type="search",
                payload={"query": query, "top_k": 5},
                conversation_id=message.conversation_id, job_id=message.job_id,
            )
        except Exception:  # noqa: BLE001
            logger.debug("vault search unavailable")

        web_results: Any = None
        web_error = None
        if want_web:
            try:
                web_results = await call_tool("brave", "brave_web_search", {"query": query, "count": 5})
            except McpGatewayError as exc:
                web_error = str(exc)
                logger.info("web search skipped: %s", web_error)

        return {
            "query": query,
            "vault_results": vault_results or [],
            "web_results": web_results,
            "web_search_unavailable": web_error,
        }
