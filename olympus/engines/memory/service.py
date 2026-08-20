"""Memory engine FastAPI service.

Endpoints:
  POST /memory/add       store memories from free text (Mem0 extraction)
  GET  /memory/search    semantic memory search
  POST /docs/ingest      RAG-ingest files into Qdrant
  GET  /docs/search      RAG search over ingested docs
  GET  /registry         provenance registry (filter by user/project/agent/source)

Run:
    uvicorn olympus.engines.memory.service:app --host 127.0.0.1 --port 5060
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .mem0_client import Mem0Client
from .ingest import RagIngestor

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "olympus" / "data" / "memory"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "memory_registry.db"

app = FastAPI(title="Memory Engine", version="1.0.0")


def _mem0() -> Mem0Client:
    return Mem0Client(llm_model="qwen3:8b", db_path=DB_PATH)


def _ingestor() -> RagIngestor:
    return RagIngestor(db_path=DB_PATH)


class AddRequest(BaseModel):
    text: str
    user_id: str = ""
    project_id: str = ""
    agent_id: str = ""
    source: str = ""
    confidence: float = 1.0
    evidence: str = ""


class SearchRequest(BaseModel):
    query: str
    user_id: str = ""
    limit: int = 5


class IngestRequest(BaseModel):
    files: list[str]
    project_id: str = ""
    agent_id: str = ""


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "memory-engine"}


@app.post("/memory/add")
def memory_add(req: AddRequest) -> dict[str, Any]:
    try:
        created = _mem0().add(
            req.text,
            user_id=req.user_id,
            project_id=req.project_id,
            agent_id=req.agent_id,
            source=req.source,
            confidence=req.confidence,
            evidence=req.evidence,
        )
        return {"created": created, "count": len(created)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e))


@app.post("/memory/search")
def memory_search(req: SearchRequest) -> dict[str, Any]:
    try:
        results = _mem0().search(req.query, user_id=req.user_id, limit=req.limit)
        return {"results": results}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e))


@app.post("/docs/ingest")
def docs_ingest(req: IngestRequest) -> dict[str, Any]:
    try:
        stats = _ingestor().ingest(
            req.files,
            project_id=req.project_id,
            agent_id=req.agent_id,
        )
        return {"status": "ok", "stats": stats}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e))


@app.post("/docs/search")
def docs_search(req: SearchRequest) -> dict[str, Any]:
    try:
        results = _ingestor().search(req.query, limit=req.limit)
        return {"results": results}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e))


@app.get("/registry")
def registry(
    user_id: str = "",
    project_id: str = "",
    agent_id: str = "",
    source: str = "",
) -> dict[str, Any]:
    from .registry import MemoryRegistry

    reg = MemoryRegistry(DB_PATH)
    try:
        rows = reg.query(
            user_id=user_id, project_id=project_id, agent_id=agent_id, source=source
        )
        return {"count": len(rows), "rows": rows}
    finally:
        reg.close()