import json
import logging

from fastapi import APIRouter, HTTPException

from app.models.job import RunRequest
from app.services import collaboration_bus as bus
from app.services.collaboration_bus import NoHandlerError
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.api.run")
router = APIRouter()

_ORCHESTRATOR_TIMEOUT = 120.0


def _create_job(goal: str, payload: dict) -> str:
    job_id = new_id()
    ts = now_iso()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO jobs (id, type, title, status, payload_json, progress, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (job_id, "compose_task", goal[:120], "queued", json.dumps(payload), 0.0, ts, ts),
        )
        conn.commit()
    finally:
        conn.close()
    return job_id


def _mark_job(job_id: str, status: str, result: dict | None = None, error: str | None = None) -> None:
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


async def _run_via_orchestrator(goal: str, context: dict, job_id: str | None = None,
                                 model: str | None = None) -> dict:
    """Dispatch to the 'orchestrator' agent over the bus. Raises KeyError
    (via collaboration_bus) if orchestrator isn't registered yet -- callers
    decide how to surface that."""
    return await bus.send_message(
        from_agent="api",
        to_agent="orchestrator",
        msg_type="run",
        payload={"goal": goal, "context": context, "model": model},
        job_id=job_id,
    )


@router.post("/run")
async def run(req: RunRequest):
    payload = {
        "goal": req.goal,
        "risk_level": req.risk_level,
        "review_policy": req.review_policy,
        "context": req.context,
        "model": req.model,
    }
    job_id = _create_job(req.goal, payload)

    if req.run_mode == "background":
        return {"job_id": job_id, "route": "queued"}

    # sync mode: try to run it now
    try:
        result = await _run_via_orchestrator(req.goal, req.context, job_id=job_id, model=req.model)
        _mark_job(job_id, "done", result={"response": result})
        return {"response": result, "job_id": job_id}
    except NoHandlerError:
        _mark_job(job_id, "failed", error="orchestrator not yet available")
        raise HTTPException(
            status_code=503,
            detail="orchestrator isn't registered yet (control-layer agents land in "
                   "a later build phase) -- the job was queued instead: " + job_id,
        )


@router.post("/run/quick")
async def run_quick(body: dict):
    goal = body.get("goal", "")
    system = body.get("system")
    model = body.get("model")
    if not goal:
        raise HTTPException(status_code=400, detail="'goal' is required")
    try:
        result = await _run_via_orchestrator(goal, {"system": system} if system else {}, model=model)
        return {"response": result}
    except NoHandlerError:
        raise HTTPException(
            status_code=503,
            detail="orchestrator isn't registered yet (control-layer agents land in a later build phase)",
        )
