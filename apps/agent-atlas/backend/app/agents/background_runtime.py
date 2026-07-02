"""
background_runtime.py  --  Polls the jobs table and executes queued jobs.

Not a BaseAgent -- it's plumbing, not something that receives messages
over the bus. start_workers() spawns a small pool of asyncio tasks that
each loop: claim one queued job (atomically, via an IMMEDIATE transaction
so two workers can't grab the same row), dispatch it to the right agent
over the collaboration bus, and record the result.

JOB_ROUTES only has one entry for now (compose_task -> orchestrator) --
more job types (research, code, automation) get routed here as their
agents are added in later build phases.
"""

import asyncio
import json
import logging
from typing import Dict, Tuple

from app.services import collaboration_bus as bus
from app.storage.database import get_connection
from app.utils.ids import now_iso

logger = logging.getLogger("agent_atlas.background_runtime")

JOB_ROUTES: Dict[str, Tuple[str, str]] = {
    "compose_task": ("orchestrator", "run"),
}

_POLL_INTERVAL_S = 2.0
_JOB_TIMEOUT_S = 1800.0  # 30 min


def _claim_next_job() -> dict | None:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, type, payload_json FROM jobs WHERE status = 'queued' "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
        conn.commit()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finish_job(job_id: str, status: str, result: dict | None = None, error: str | None = None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE jobs SET status=?, result_json=?, error=?, progress=?, updated_at=? WHERE id=?",
            (status, json.dumps(result) if result is not None else None, error,
             1.0 if status == "done" else 0.0, now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


async def _execute(job: dict) -> None:
    job_id, job_type = job["id"], job["type"]
    route = JOB_ROUTES.get(job_type)
    if route is None:
        _finish_job(job_id, "failed", error=f"no route for job type '{job_type}'")
        await bus.broadcast({"event": "job_update", "job_id": job_id, "status": "failed"})
        return

    to_agent, msg_type = route
    payload = json.loads(job["payload_json"] or "{}")
    try:
        result = await asyncio.wait_for(
            bus.send_message(from_agent="worker", to_agent=to_agent, msg_type=msg_type,
                              payload=payload, job_id=job_id),
            timeout=_JOB_TIMEOUT_S,
        )
        _finish_job(job_id, "done", result={"response": result})
        await bus.broadcast({"event": "job_update", "job_id": job_id, "status": "done"})
    except asyncio.TimeoutError:
        _finish_job(job_id, "failed", error=f"timed out after {_JOB_TIMEOUT_S:.0f}s")
        await bus.broadcast({"event": "job_update", "job_id": job_id, "status": "failed"})
    except Exception as exc:  # noqa: BLE001
        logger.exception("job %s failed", job_id)
        _finish_job(job_id, "failed", error=str(exc))
        await bus.broadcast({"event": "job_update", "job_id": job_id, "status": "failed"})


async def _worker_loop(worker_name: str, stop_event: asyncio.Event) -> None:
    logger.info("%s started", worker_name)
    while not stop_event.is_set():
        try:
            job = await asyncio.to_thread(_claim_next_job)
        except Exception:  # noqa: BLE001
            logger.exception("%s: failed to poll for jobs", worker_name)
            job = None

        if job is None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=_POLL_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
            continue

        logger.info("%s claimed job %s (%s)", worker_name, job["id"], job["type"])
        await _execute(job)
    logger.info("%s stopped", worker_name)


_tasks: list[asyncio.Task] = []
_stop_event: asyncio.Event | None = None


def start_workers(n: int = 2) -> None:
    global _stop_event
    _stop_event = asyncio.Event()
    for i in range(n):
        _tasks.append(asyncio.create_task(_worker_loop(f"worker-{i}", _stop_event)))


async def stop_workers() -> None:
    if _stop_event is not None:
        _stop_event.set()
    for t in _tasks:
        await t
    _tasks.clear()
