import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.job import Job, JobCreateRequest, JobUpdateRequest
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.api.jobs")
router = APIRouter()


def _row_to_job(row) -> Dict[str, Any]:
    keys = row.keys()
    return {
        "id": row["id"],
        "type": row["type"],
        "title": row["title"] if "title" in keys else None,
        "status": row["status"],
        "payload": json.loads(row["payload_json"] or "{}"),
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "progress": row["progress"],
        "error": row["error"],
        "notes": row["notes"] if "notes" in keys else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class NotesRequest(BaseModel):
    notes: str


@router.get("/", response_model=List[Dict[str, Any]])
async def list_jobs(status: Optional[str] = None, limit: int = 50):
    conn = get_connection()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    finally:
        conn.close()
    return [_row_to_job(r) for r in rows]


@router.get("/{job_id}", response_model=Dict[str, Any])
async def get_job(job_id: str):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return _row_to_job(row)


@router.post("/", status_code=201, response_model=Dict[str, Any])
async def create_job(req: JobCreateRequest):
    job_id = new_id()
    ts = now_iso()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO jobs (id, type, title, status, payload_json, progress, created_at, updated_at)
               VALUES (?, ?, ?, 'queued', ?, 0, ?, ?)""",
            (job_id, req.type, req.title, json.dumps(req.payload), ts, ts),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": job_id, "status": "queued"}


@router.patch("/{job_id}", response_model=Dict[str, Any])
async def update_job(job_id: str, req: JobUpdateRequest):
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

        updates = []
        values: List[Any] = []
        if req.title is not None:
            updates.append("title = ?")
            values.append(req.title)
        if req.type is not None:
            updates.append("type = ?")
            values.append(req.type)

        if updates:
            updates.append("updated_at = ?")
            values.append(now_iso())
            values.append(job_id)
            conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()

        result = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_job(result)


def _set_status(job_id: str, new_status: str):
    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": job_id, "status": new_status}


@router.post("/{job_id}/pause")
async def pause_job(job_id: str):
    return _set_status(job_id, "paused")


@router.post("/{job_id}/resume")
async def resume_job(job_id: str):
    return _set_status(job_id, "queued")


@router.post("/{job_id}/stop")
async def stop_job(job_id: str):
    return _set_status(job_id, "stopped")


@router.post("/{job_id}/retry")
async def retry_job(job_id: str):
    """Re-queue a failed or stopped job so the background worker picks it up again."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        if row["status"] not in ("failed", "stopped", "done"):
            raise HTTPException(
                status_code=409,
                detail=f"Job is '{row['status']}' — only failed, stopped, or done jobs can be retried",
            )
        conn.execute(
            "UPDATE jobs SET status = 'queued', error = NULL, progress = 0, result_json = NULL, updated_at = ? WHERE id = ?",
            (now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": job_id, "status": "queued"}


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str):
    """Permanently delete a job record."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
    finally:
        conn.close()


@router.patch("/{job_id}/notes")
async def save_notes(job_id: str, req: NotesRequest):
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        conn.execute(
            "UPDATE jobs SET notes = ?, updated_at = ? WHERE id = ?",
            (req.notes, now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": job_id, "notes": req.notes}
