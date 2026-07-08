from typing import Any, Dict

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.services import obsidian_indexer


class ObsidianBrainAgent(BaseAgent):
    agent_id = "obsidian_brain"

    async def handle(self, message: AgentMessage) -> Any:
        if message.type == "search":
            query = message.payload.get("query", "")
            top_k = message.payload.get("top_k", 5)
            return await obsidian_indexer.search_notes(query, top_k)

        if message.type == "reindex":
            count = await obsidian_indexer.index_vault()
            return {"indexed": count}

        if message.type == "summarize":
            note_ids = message.payload.get("note_ids", [])
            results = await obsidian_indexer.search_notes(message.payload.get("query", ""), top_k=len(note_ids) or 5)
            snippets = "\n\n".join(f"- {r['title']}: {r['snippet']}" for r in results)
            return await self.llm_call(
                f"Summarise these notes:\n\n{snippets}",
                system="Summarise concisely, grouped by theme if there's more than one.",
            )

        # default: treat payload.goal as a search query
        query = message.payload.get("goal") or message.payload.get("query", "")
        return await obsidian_indexer.search_notes(query, 5)
