import json
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import obsidian_indexer
from app.storage.database import get_connection

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


@router.get("/notes")
async def list_notes(limit: int = 100):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, path, title, tags, indexed_at FROM obsidian_notes "
            "ORDER BY indexed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
        result.append(d)
    return result


@router.post("/search")
async def search(req: SearchRequest) -> Dict[str, Any]:
    results = await obsidian_indexer.search_notes(req.query, req.top_k)
    return {"query": req.query, "results": results}


@router.post("/index")
async def reindex() -> Dict[str, Any]:
    count = await obsidian_indexer.index_vault()
    return {"status": "done", "indexed": count}
