"""Tests for the job queue CRUD and status transitions."""
import json
import pytest

from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso


def _create_job(job_type: str = "test", payload: dict = None) -> str:
    job_id = new_id()
    ts = now_iso()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO jobs (id, type, status, payload_json, progress, created_at, updated_at) VALUES (?, ?, 'queued', ?, 0, ?, ?)",
            (job_id, job_type, json.dumps(payload or {}), ts, ts),
        )
        conn.commit()
    finally:
        conn.close()
    return job_id


def _get_job(job_id: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else {}


def test_create_job():
    job_id = _create_job("research", {"query": "hello"})
    job = _get_job(job_id)
    assert job["status"] == "queued"
    assert job["type"] == "research"


def test_status_transitions():
    job_id = _create_job()
    conn = get_connection()
    try:
        def set_status(status):
            conn.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), job_id))
            conn.commit()

        set_status("running")
        assert _get_job(job_id)["status"] == "running"

        set_status("paused")
        assert _get_job(job_id)["status"] == "paused"

        set_status("queued")
        assert _get_job(job_id)["status"] == "queued"

        set_status("done")
        assert _get_job(job_id)["status"] == "done"
    finally:
        conn.close()


def test_multiple_jobs_ordered():
    ids = [_create_job(f"type_{i}") for i in range(5)]
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id FROM jobs ORDER BY created_at").fetchall()
    finally:
        conn.close()
    row_ids = [r["id"] for r in rows]
    for job_id in ids:
        assert job_id in row_ids


def test_job_result_stored():
    job_id = _create_job()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE jobs SET status='done', result_json=?, progress=1.0, updated_at=? WHERE id=?",
            (json.dumps({"answer": 42}), now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()
    job = _get_job(job_id)
    result = json.loads(job["result_json"])
    assert result["answer"] == 42
