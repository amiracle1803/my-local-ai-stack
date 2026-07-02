import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.agents.observability")


class ObservabilityAgent(BaseAgent):
    agent_id = "observability_agent"

    async def handle(self, message: AgentMessage) -> Any:
        op = message.payload.get("op", "metrics")
        if op == "record":
            return self._record(message.payload)
        if op == "metrics":
            return self._get_metrics(message.payload.get("agent_id"))
        if op == "traces":
            return self._get_traces(message.payload.get("agent_id"))
        return {"error": f"Unknown op: {op}"}

    def _record(self, payload: dict) -> dict:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO metrics (id, agent_id, metric, value, timestamp) VALUES (?, ?, ?, ?, ?)",
                (new_id(), payload.get("agent_id", ""), payload.get("metric", ""), payload.get("value", 0), now_iso()),
            )
            conn.commit()
        finally:
            conn.close()
        return {"status": "recorded"}

    def _get_metrics(self, agent_id: str = None) -> dict:
        conn = get_connection()
        try:
            if agent_id:
                rows = conn.execute(
                    "SELECT agent_id, metric, AVG(value) as avg_value, COUNT(*) as count FROM metrics WHERE agent_id = ? GROUP BY agent_id, metric",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT agent_id, metric, AVG(value) as avg_value, COUNT(*) as count FROM metrics GROUP BY agent_id, metric"
                ).fetchall()
        finally:
            conn.close()
        return {"metrics": [dict(r) for r in rows]}

    def _get_traces(self, agent_id: str = None) -> dict:
        conn = get_connection()
        try:
            if agent_id:
                rows = conn.execute(
                    "SELECT id, agent_id, model_used, duration_ms, success, created_at FROM agent_traces WHERE agent_id = ? ORDER BY created_at DESC LIMIT 50",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, agent_id, model_used, duration_ms, success, created_at FROM agent_traces ORDER BY created_at DESC LIMIT 50"
                ).fetchall()
        finally:
            conn.close()
        return {"traces": [dict(r) for r in rows]}
