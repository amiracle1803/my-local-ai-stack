import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.agents.automation_agent")


class AutomationAgent(BaseAgent):
    agent_id = "automation_agent"

    async def handle(self, message: AgentMessage) -> Any:
        op = message.payload.get("op")

        # Subtask from orchestrator: {task: "...", goal: "..."} — no "op" key
        if op is None and ("task" in message.payload or "goal" in message.payload):
            task = message.payload.get("task", "") or message.payload.get("goal", "")
            task_lower = task.lower()
            if any(kw in task_lower for kw in ("list", "show", "status", "check", "what jobs")):
                return self._list_jobs()
            # Map task intent to a job type
            job_type = "automation"
            for kw, jtype in (
                ("research", "research"), ("search", "research"),
                ("code", "code"), ("script", "code"), ("program", "code"),
                ("creative", "creative"), ("write", "creative"),
                ("deploy", "deploy"), ("obsidian", "obsidian"),
            ):
                if kw in task_lower:
                    job_type = jtype
                    break
            return self._schedule_job({"type": job_type, "job_payload": {"goal": task}})

        op = op or "schedule"
        if op == "schedule":
            return self._schedule_job(message.payload)
        if op == "list":
            return self._list_jobs()
        return {"error": f"Unknown op: {op}"}

    def _schedule_job(self, payload: dict) -> dict:
        job_type = payload.get("type", "automation")
        job_payload = payload.get("job_payload", {})
        job_id = new_id()
        ts = now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO jobs (id, type, status, payload_json, progress, created_at, updated_at)
                   VALUES (?, ?, 'queued', ?, 0, ?, ?)""",
                (job_id, job_type, json.dumps(job_payload), ts, ts),
            )
            conn.commit()
        finally:
            conn.close()
        logger.info("[automation_agent] Scheduled job %s (type=%s)", job_id, job_type)
        return {"job_id": job_id, "status": "queued"}

    def _list_jobs(self) -> dict:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id, type, status, created_at FROM jobs ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
        finally:
            conn.close()
        return {"jobs": [dict(r) for r in rows]}
