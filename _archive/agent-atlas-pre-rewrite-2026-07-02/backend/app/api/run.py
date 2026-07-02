"""
POST /run    — main user-facing endpoint (orchestrator pipeline).
POST /run/quick — bypass orchestrator; direct single-LLM call for instant replies.

Both endpoints create a Job record so the task appears in the Tasks view.
"""
import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import collaboration_bus as bus
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.api.run")
router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    goal: str
    context: Dict[str, Any] = {}
    run_mode: str = "sync"              # sync | background
    risk_level: str = "low"            # low | medium | high | critical
    review_policy: str = "low_risk_quick"


class QuickRunRequest(BaseModel):
    goal: str
    system: Optional[str] = None       # optional system prompt override


class RunResponse(BaseModel):
    response: Any
    route: Optional[str] = None
    conversation_id: Optional[str] = None
    job_id: Optional[str] = None       # always present so frontend can link to Tasks


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_to_obsidian(goal: str, response: Any, route: str) -> None:
    """Append this run to today's Obsidian session log. Never raises."""
    try:
        from app.services.obsidian_indexer import append_daily_note
        append_daily_note(goal, str(response), route)
    except Exception as exc:
        logger.warning("Obsidian save skipped: %s", exc)


def _create_job(job_id: str, goal: str, risk_level: str, status: str = "running") -> None:
    """Insert a job row so this task appears in the Tasks view."""
    ts = now_iso()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO jobs (id, type, title, status, payload_json, progress, created_at, updated_at)
               VALUES (?, 'compose_task', ?, ?, ?, 0, ?, ?)""",
            (
                job_id,
                goal[:120],                          # title (truncated)
                status,
                json.dumps({"goal": goal, "risk_level": risk_level}),
                ts,
                ts,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _finish_job(job_id: str, result: Any, success: bool = True) -> None:
    """Mark a job done (or failed) and store the result."""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE jobs
               SET status = ?, result_json = ?, progress = 1.0, updated_at = ?
               WHERE id = ?""",
            (
                "done" if success else "failed",
                json.dumps(result, default=str),
                now_iso(),
                job_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ── Routes ────────────────────────────────────────────────────────────────────

_SYNC_TIMEOUT_SECONDS = 300  # 5-minute hard cap; use background mode for longer tasks


@router.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    job_id = new_id()

    if req.run_mode == "background":
        # Create directly as "queued" — the background worker picks it up.
        _create_job(job_id, req.goal, req.risk_level, status="queued")
        return RunResponse(
            response="Task queued for background execution.",
            route="background",
            job_id=job_id,
        )

    _create_job(job_id, req.goal, req.risk_level, status="running")

    try:
        result = await asyncio.wait_for(
            bus.send_message(
                from_agent="user",
                to_agent="orchestrator",
                msg_type="user_goal",
                payload={
                    "goal": req.goal,
                    "context": req.context,
                    "risk_level": req.risk_level,
                    "review_policy": req.review_policy,
                },
                runtime_mode=req.run_mode,
                user_visible=True,
            ),
            timeout=_SYNC_TIMEOUT_SECONDS,
        )

        _finish_job(job_id, result, success=True)

        if isinstance(result, dict) and "response" in result:
            resp_text = result["response"]
            route = result.get("route", "orchestrator")
            _save_to_obsidian(req.goal, resp_text, route)
            return RunResponse(response=resp_text, route=route, job_id=job_id)
        _save_to_obsidian(req.goal, result, "orchestrator")
        return RunResponse(response=result, job_id=job_id)

    except asyncio.TimeoutError:
        _finish_job(job_id, {"error": "Request timed out"}, success=False)
        raise HTTPException(
            status_code=504,
            detail=f"Orchestrator timed out after {_SYNC_TIMEOUT_SECONDS}s — use background mode for long tasks",
        )

    except asyncio.CancelledError:
        # Client disconnected mid-request; mark job failed so it doesn't stay "running".
        _finish_job(job_id, {"error": "Request cancelled by client"}, success=False)
        raise  # Let FastAPI/Starlette handle the cancellation

    except (ValueError, RuntimeError) as exc:
        _finish_job(job_id, {"error": str(exc)}, success=False)
        raise HTTPException(status_code=502, detail=str(exc))

    except Exception as exc:
        _finish_job(job_id, {"error": str(exc)}, success=False)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/run/quick", response_model=RunResponse)
async def run_quick(req: QuickRunRequest):
    """Direct single-LLM call — no orchestrator, no planner. Instant replies."""
    from app.services.model_router import get_best_client

    job_id = new_id()
    _create_job(job_id, req.goal, "low", status="running")

    try:
        client = await get_best_client()
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.goal})
        result = await client.chat(messages)
        content = result.get("content", "")
        _finish_job(job_id, {"response": content}, success=True)
        _save_to_obsidian(req.goal, content, "quick")
        return RunResponse(response=content, route="quick", job_id=job_id)
    except asyncio.CancelledError:
        _finish_job(job_id, {"error": "Request cancelled by client"}, success=False)
        raise
    except Exception as exc:
        _finish_job(job_id, {"error": str(exc)}, success=False)
        raise HTTPException(status_code=502, detail=str(exc))
