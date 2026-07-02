import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from app.models.job import JobCreateRequest, JobUpdateRequest
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

router = APIRouter()


def _row_to_job(row) -> Dict[str, Any]:
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json") or "{}")
    result_json = d.pop("result_json")
    d["result"] = json.loads(result_json) if result_json else None
    return d


@router.get("/", response_model=List[Dict[str, Any]])
async def list_jobs(status: Optional[str] = None, limit: int = 200):
    conn = get_connection()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,),
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


@router.post("/", status_code=201)
async def create_job(req: JobCreateRequest):
    job_id = new_id()
    ts = now_iso()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO jobs (id, type, title, status, payload_json, progress, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (job_id, req.type, req.title, "queued", json.dumps(req.payload), 0.0, ts, ts),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": job_id, "status": "queued"}


@router.patch("/{job_id}", response_model=Dict[str, Any])
async def update_job(job_id: str, req: JobUpdateRequest):
    fields, values = [], []
    if req.title is not None:
        fields.append("title = ?")
        values.append(req.title)
    if req.type is not None:
        fields.append("type = ?")
        values.append(req.type)
    if not fields:
        return await get_job(job_id)

    fields.append("updated_at = ?")
    values.append(now_iso())
    values.append(job_id)

    conn = get_connection()
    try:
        cur = conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    finally:
        conn.close()
    return await get_job(job_id)


@router.patch("/{job_id}/notes", response_model=Dict[str, Any])
async def save_notes(job_id: str, body: Dict[str, str]):
    notes = body.get("notes", "")
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE jobs SET notes = ?, updated_at = ? WHERE id = ?",
            (notes, now_iso(), job_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    finally:
        conn.close()
    return {"id": job_id, "notes": notes}


def _set_status(job_id: str, status: str, allowed_from: Optional[List[str]] = None) -> Dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        if allowed_from and row["status"] not in allowed_from:
            raise HTTPException(
                status_code=409,
                detail=f"Job is '{row['status']}', can't transition to '{status}' from there",
            )
        conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": job_id, "status": status}


@router.post("/{job_id}/pause")
async def pause_job(job_id: str):
    return _set_status(job_id, "paused", allowed_from=["queued", "running"])


@router.post("/{job_id}/resume")
async def resume_job(job_id: str):
    return _set_status(job_id, "queued", allowed_from=["paused"])


@router.post("/{job_id}/stop")
async def stop_job(job_id: str):
    return _set_status(job_id, "stopped", allowed_from=["queued", "running", "paused"])


@router.post("/{job_id}/retry")
async def retry_job(job_id: str):
    return _set_status(job_id, "queued", allowed_from=["failed", "stopped", "done"])


@router.delete("/{job_id}")
async def delete_job(job_id: str):
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    finally:
        conn.close()
    return {"status": "deleted", "id": job_id}
