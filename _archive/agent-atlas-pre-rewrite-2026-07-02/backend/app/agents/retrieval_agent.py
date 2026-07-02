import asyncio
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.services.vector_store import query as vec_query

logger = logging.getLogger("agent_atlas.agents.retrieval_agent")


class RetrievalAgent(BaseAgent):
    agent_id = "retrieval_agent"

    async def handle(self, message: AgentMessage) -> Any:
        query_text = message.payload.get("query", "")
        collection = message.payload.get("collection", "obsidian")
        top_k = message.payload.get("top_k", 5)
        logger.info("[retrieval_agent] Query: '%s' in '%s'", query_text[:60], collection)

        # Both operations are synchronous (ChromaDB / SQLite) — run them in
        # threads so they don't block the event loop.
        semantic_results, keyword_results = await asyncio.gather(
            asyncio.to_thread(vec_query, collection, query_text, top_k),
            asyncio.to_thread(self._keyword_search, query_text, top_k),
        )

        # Merge and deduplicate by id
        seen = set()
        merged = []
        for r in semantic_results + keyword_results:
            if r["id"] not in seen:
                seen.add(r["id"])
                merged.append(r)

        return {"results": merged[:top_k], "query": query_text}

    def _keyword_search(self, query: str, top_k: int) -> list:
        from app.storage.database import get_connection
        # Escape LIKE wildcards that appear *inside* the user query so that
        # a query like "50%" doesn't accidentally match everything.
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id, path, title FROM obsidian_notes WHERE title LIKE ? ESCAPE '\\' LIMIT ?",
                (pattern, top_k),
            ).fetchall()
        finally:
            conn.close()
        # Use the file path as the id to match what the vector store returns,
        # so the caller's deduplication-by-id loop works across both result sets.
        return [{"id": r["path"], "text": r["title"], "metadata": {"path": r["path"]}, "score": 0.5}
                for r in rows]
