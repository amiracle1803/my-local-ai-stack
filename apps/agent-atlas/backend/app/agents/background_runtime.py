"""
Background Runtime: polls the jobs table and executes queued jobs.
Supports N parallel workers. Uses BEGIN IMMEDIATE to atomically claim jobs,
preventing two workers from picking the same row.
"""
import asyncio
import json
import logging
from typing import Any, Dict

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.storage.database import get_connection
from app.utils.ids import now_iso

logger = logging.getLogger("agent_atlas.background_runtime")

_running = False
_worker_tasks: list[asyncio.Task] = []

# Maps job type → (to_agent, msg_type)
JOB_ROUTES: Dict[str, tuple[str, str]] = {
    "research":     ("knowledge_hub",        "research_request"),
    "code":         ("code_agent",           "code_request"),
    "automation":   ("automation_agent",     "schedule"),
    "obsidian":     ("obsidian_brain",       "search"),
    "evaluate":     ("evaluator",            "evaluate_request"),
    "creative":     ("creative_studio_agent","create_doc"),
    "train":        ("local_model_trainer",  "prepare"),
    "deploy":       ("deployment_agent",     "status"),
}


async def _run_worker(worker_id: int, poll_interval: float = 2.0):
    global _running
    logger.info("Worker-%d started (poll=%.1fs)", worker_id, poll_interval)
    while _running:
        try:
            claimed = await _claim_and_run_job(worker_id)
            if not claimed:
                # Nothing ready — wait before polling again
                await asyncio.sleep(poll_interval)
        except Exception as exc:
            logger.error("Worker-%d loop error: %s", worker_id, exc)
            await asyncio.sleep(poll_interval)
    logger.info("Worker-%d stopped.", worker_id)


async def _claim_and_run_job(worker_id: int) -> bool:
    """Atomically claim one queued job and execute it. Returns True if a job was found."""
    conn = get_connection()
    try:
        # BEGIN IMMEDIATE gets a write lock before we SELECT, preventing double-claim
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, type, payload_json FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            conn.rollback()
            return False

        job_id = row["id"]
        job_type = row["type"]
        payload = json.loads(row["payload_json"] or "{}")

        conn.execute(
            "UPDATE jobs SET status='running', updated_at=? WHERE id=?",
            (now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info("Worker-%d claimed job %s (type=%s)", worker_id, job_id, job_type)
    try:
        result = await _dispatch_job(job_type, payload, job_id)
        _finish_job(job_id, "done", result=result)
    except Exception as exc:
        logger.error("Worker-%d job %s failed: %s", worker_id, job_id, exc)
        _finish_job(job_id, "failed", error=str(exc))
    return True


_JOB_TIMEOUT_SECONDS = 1800  # 30-minute cap; prevents a hung agent from stalling a worker forever


async def _dispatch_job(job_type: str, payload: dict, job_id: str) -> dict:
    from app.services import collaboration_bus as bus

    # Generic goal tasks (submitted via /run with run_mode=background) go through
    # the full orchestrator pipeline, same as the sync /run endpoint.
    if job_type == "compose_task":
        goal = payload.get("goal", "")
        result = await asyncio.wait_for(
            bus.send_message(
                from_agent="background_runtime",
                to_agent="orchestrator",
                msg_type="user_goal",
                payload={
                    "goal": goal,
                    "context": payload.get("context", {}),
                    "risk_level": payload.get("risk_level", "low"),
                    "review_policy": payload.get("review_policy", "low_risk_quick"),
                    "_job_id": job_id,
                },
                runtime_mode="background",
            ),
            timeout=_JOB_TIMEOUT_SECONDS,
        )
        return result if isinstance(result, dict) else {"result": result}

    if job_type in JOB_ROUTES:
        to_agent, msg_type = JOB_ROUTES[job_type]
        payload["_job_id"] = job_id
        result = await asyncio.wait_for(
            bus.send_message(
                from_agent="background_runtime",
                to_agent=to_agent,
                msg_type=msg_type,
                payload=payload,
                runtime_mode="background",
            ),
            timeout=_JOB_TIMEOUT_SECONDS,
        )
        return result if isinstance(result, dict) else {"result": result}

    logger.warning("No route for job type '%s' — completing as stub.", job_type)
    return {"message": f"No handler registered for job type '{job_type}'"}


def _finish_job(job_id: str, status: str, result: dict = None, error: str = None):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE jobs SET status=?, result_json=?, error=?, progress=1.0, updated_at=? WHERE id=?",
            (status, json.dumps(result) if result else None, error, now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()
    asyncio.create_task(
        _broadcast({"event": "job_update", "job_id": job_id, "status": status})
    )


async def _broadcast(data: dict):
    try:
        from app.services import ws_bus
        await ws_bus.broadcast(data)
    except Exception:
        pass


# ── Public control API ────────────────────────────────────────────────────────

def start_worker(n: int = 4):
    """Start N parallel background workers."""
    global _running, _worker_tasks
    if _worker_tasks and any(not t.done() for t in _worker_tasks):
        logger.warning("Workers already running — skipping start.")
        return
    _running = True
    _worker_tasks = [asyncio.create_task(_run_worker(i)) for i in range(n)]
    logger.info("Started %d background workers.", n)


def stop_worker():
    global _running, _worker_tasks
    _running = False
    for t in _worker_tasks:
        if not t.done():
            t.cancel()
    _worker_tasks = []


# ── Agent interface ────────────────────────────────────────────────────────────

class BackgroundRuntimeAgent(BaseAgent):
    agent_id = "background_runtime"

    async def handle(self, message: AgentMessage) -> Any:
        op = message.payload.get("op", "status")
        if op == "start":
            start_worker()
            return {"status": "workers started"}
        if op == "stop":
            stop_worker()
            return {"status": "workers stopping"}
        alive = sum(1 for t in _worker_tasks if not t.done())
        return {"running": _running, "workers_alive": alive, "total_workers": len(_worker_tasks)}
