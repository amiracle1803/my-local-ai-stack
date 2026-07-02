"""
GET /metrics — Observability API consumed by the frontend Logs page.
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter

from app.storage.database import get_connection

logger = logging.getLogger("agent_atlas.api.metrics")
router = APIRouter()


@router.get("/metrics/agents")
async def agent_metrics() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT agent_id,
                      COUNT(*) as call_count,
                      AVG(duration_ms) as avg_latency_ms,
                      SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                      SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failures
               FROM agent_traces
               GROUP BY agent_id
               ORDER BY call_count DESC"""
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@router.get("/metrics/models")
async def model_metrics() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT model_used,
                      COUNT(*) as call_count,
                      AVG(duration_ms) as avg_latency_ms
               FROM agent_traces
               WHERE model_used IS NOT NULL
               GROUP BY model_used
               ORDER BY call_count DESC"""
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@router.get("/metrics/errors")
async def recent_errors(limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, agent_id, input_json, created_at
               FROM agent_traces
               WHERE success = 0
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
