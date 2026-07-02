import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import obsidian_indexer
from app.storage.database import get_connection

logger = logging.getLogger("agent_atlas.api.obsidian")
router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class AppendRequest(BaseModel):
    path: str
    content: str


@router.get("/notes")
async def list_notes(limit: int = 100):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, path, title, tags, indexed_at FROM obsidian_notes ORDER BY indexed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        row = dict(r)
        # tags is stored as a JSON array string — parse it before returning
        try:
            row["tags"] = json.loads(row.get("tags") or "[]")
        except (json.JSONDecodeError, TypeError):
            row["tags"] = []
        result.append(row)
    return result


@router.post("/search")
async def search_notes(req: SearchRequest):
    results = await asyncio.to_thread(obsidian_indexer.search_notes, req.query, req.top_k)
    return {"query": req.query, "results": results}


@router.post("/index")
async def trigger_index():
    """Manually trigger a vault re-index (offloaded to thread — file I/O is blocking)."""
    count = await asyncio.to_thread(obsidian_indexer.index_vault)
    return {"status": "done", "indexed": count}


@router.post("/append")
async def append_to_note(req: AppendRequest):
    ok = await asyncio.to_thread(obsidian_indexer.append_to_note, req.path, req.content)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Note not found: {req.path}")
    return {"status": "appended"}
