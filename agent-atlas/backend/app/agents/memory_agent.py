import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.agents.memory_agent")


class MemoryAgent(BaseAgent):
    agent_id = "memory_agent"

    async def handle(self, message: AgentMessage) -> Any:
        op = message.payload.get("op", "get")
        if op == "save_episode":
            return self._save_episode(message.payload)
        if op == "get_profile":
            return self._get_profile(message.payload.get("user_id", "default"))
        if op == "set_profile":
            return self._set_profile(message.payload)
        if op == "save_fact":
            return self._save_fact(message.payload)
        if op == "get_context":
            return self._get_context(message.payload.get("limit", 5))
        return {"error": f"Unknown op: {op}"}

    def _save_episode(self, payload: dict) -> dict:
        """Persist episode to SQLite and mirror it to Obsidian."""
        ep_id = new_id()
        project_id = payload.get("project_id") or "default"
        summary = payload.get("summary", "")
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO memory_episodes (id, project_id, summary, created_at) VALUES (?, ?, ?, ?)",
                (ep_id, project_id, summary, now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

        # Mirror to Obsidian
        try:
            from app.services.obsidian_indexer import create_project_note
            create_project_note(project_id, summary)
        except Exception as exc:
            logger.warning("Obsidian episode mirror failed: %s", exc)

        return {"id": ep_id, "status": "saved"}

    def _save_fact(self, payload: dict) -> dict:
        """Save a named fact to Obsidian profile notes + SQLite memory_profile."""
        category = payload.get("category", "general")
        key = payload.get("key", "")
        value = payload.get("value", "")
        if not key:
            return {"error": "key required"}

        # Write to SQLite
        self._set_profile({"user_id": "default", "key": f"{category}/{key}", "value": value})

        # Mirror to Obsidian
        try:
            from app.services.obsidian_indexer import save_memory_fact
            save_memory_fact(category, key, str(value))
        except Exception as exc:
            logger.warning("Obsidian fact mirror failed: %s", exc)

        return {"status": "saved", "category": category, "key": key}

    def _get_context(self, limit: int = 5) -> dict:
        """Return recent episodes + profile facts as context for the LLM."""
        conn = get_connection()
        try:
            episodes = conn.execute(
                "SELECT project_id, summary, created_at FROM memory_episodes ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            profile = conn.execute(
                "SELECT key, value FROM memory_profile WHERE user_id = 'default' ORDER BY updated_at DESC LIMIT 20",
            ).fetchall()
        finally:
            conn.close()
        return {
            "recent_episodes": [dict(r) for r in episodes],
            "profile": {r["key"]: r["value"] for r in profile},
        }

    def _get_profile(self, user_id: str) -> dict:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT key, value FROM memory_profile WHERE user_id = ?", (user_id,)
            ).fetchall()
        finally:
            conn.close()
        return {r["key"]: r["value"] for r in rows}

    def _set_profile(self, payload: dict) -> dict:
        user_id = payload.get("user_id", "default")
        key = payload.get("key")
        value = payload.get("value")
        ts = now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO memory_profile (user_id, key, value, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (user_id, key, json.dumps(value), ts, ts),
            )
            conn.commit()
        finally:
            conn.close()
        return {"status": "set", "key": key}
