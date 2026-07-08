from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso


class MemoryAgent(BaseAgent):
    agent_id = "memory_agent"

    async def handle(self, message: AgentMessage) -> Any:
        t = message.type
        p = message.payload

        if t == "save_profile":
            return self._upsert("memory_profile", "user_id", p.get("user_id", "default"), p["key"], p["value"])
        if t == "get_profile":
            return self._get_all("memory_profile", "user_id", p.get("user_id", "default"))

        if t == "save_project":
            return self._upsert("memory_projects", "project_id", p["project_id"], p["key"], p["value"])
        if t == "get_project":
            return self._get_all("memory_projects", "project_id", p["project_id"])

        if t == "save_episode":
            return self._save_episode(p.get("project_id"), p["summary"])
        if t == "get_episodes":
            return self._get_episodes(p.get("project_id"))

        return {"error": f"unknown memory message type '{t}'"}

    def _upsert(self, table: str, scope_col: str, scope_val: str, key: str, value: Any) -> Dict[str, Any]:
        conn = get_connection()
        try:
            ts = now_iso()
            conn.execute(
                f"""INSERT INTO {table} ({scope_col}, key, value, created_at, updated_at)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT({scope_col}, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (scope_val, key, str(value), ts, ts),
            )
            conn.commit()
        finally:
            conn.close()
        return {"status": "saved", "key": key}

    def _get_all(self, table: str, scope_col: str, scope_val: str) -> Dict[str, str]:
        conn = get_connection()
        try:
            rows = conn.execute(
                f"SELECT key, value FROM {table} WHERE {scope_col} = ?", (scope_val,)
            ).fetchall()
        finally:
            conn.close()
        return {r["key"]: r["value"] for r in rows}

    def _save_episode(self, project_id: str | None, summary: str) -> Dict[str, Any]:
        conn = get_connection()
        try:
            episode_id = new_id()
            conn.execute(
                "INSERT INTO memory_episodes (id, project_id, summary, created_at) VALUES (?,?,?,?)",
                (episode_id, project_id, summary, now_iso()),
            )
            conn.commit()
        finally:
            conn.close()
        return {"status": "saved", "id": episode_id}

    def _get_episodes(self, project_id: str | None) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            if project_id:
                rows = conn.execute(
                    "SELECT id, summary, created_at FROM memory_episodes WHERE project_id = ? ORDER BY created_at DESC",
                    (project_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, summary, created_at FROM memory_episodes ORDER BY created_at DESC LIMIT 50"
                ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
