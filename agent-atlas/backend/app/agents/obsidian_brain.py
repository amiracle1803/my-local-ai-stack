import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.services.obsidian_indexer import search_notes, append_to_note

logger = logging.getLogger("agent_atlas.agents.obsidian_brain")


class ObsidianBrainAgent(BaseAgent):
    agent_id = "obsidian_brain"

    async def handle(self, message: AgentMessage) -> Any:
        op = message.payload.get("op", "search")
        if op == "search":
            query = message.payload.get("query", "")
            top_k = message.payload.get("top_k", 5)
            results = search_notes(query, top_k=top_k)
            return {"results": results, "query": query}

        if op == "summarize":
            note_ids = message.payload.get("note_ids", [])
            summaries = await self._summarize(note_ids)
            return {"summaries": summaries}

        if op == "append":
            path = message.payload.get("path", "")
            content = message.payload.get("content", "")
            ok = append_to_note(path, content)
            return {"status": "appended" if ok else "not_found"}

        return {"error": f"Unknown op: {op}"}

    async def _summarize(self, note_ids: list) -> list:
        from app.storage.database import get_connection
        # Fetch all rows first so the connection is closed before any awaits.
        conn = get_connection()
        try:
            rows = {
                note_id: conn.execute(
                    "SELECT title, path FROM obsidian_notes WHERE id = ?", (note_id,)
                ).fetchone()
                for note_id in note_ids
            }
        finally:
            conn.close()

        summaries = []
        for note_id, row in rows.items():
            if row:
                summary = await self.llm_call(
                    f"Summarize the note titled '{row['title']}' in 2-3 sentences.",
                    max_tokens=150,
                )
                summaries.append({"id": note_id, "title": row["title"], "summary": summary})
        return summaries
