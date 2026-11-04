"""RAG ingestion: documents → chunks → embeddings → Qdrant + registry.

Reads text/markdown/code files, chunks them, embeds with Ollama
(nomic-embed-text), and upserts into Qdrant. Each chunk also gets a registry
row tying it to its source file and project for provenance.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from .registry import MemoryRegistry

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
EMBED_DIM = 768  # nomic-embed-text


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        if end == n:
            break
        start = end - overlap
    return chunks


class RagIngestor:
    def __init__(
        self,
        *,
        ollama_url: str = "http://localhost:11434",
        embed_model: str = "nomic-embed-text",
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        collection: str = "docs",
        db_path: str | Path = "memory_registry.db",
    ):
        from ollama import Client

        self.ollama = Client(host=ollama_url)
        self.embed_model = embed_model
        self.qdrant = QdrantClient(host=qdrant_host, port=qdrant_port)
        self.collection = collection
        self.registry = MemoryRegistry(db_path)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        existing = self.qdrant.get_collections().collections
        if not any(c.name == self.collection for c in existing):
            self.qdrant.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
            )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            resp = self.ollama.embed(model=self.embed_model, input=t)
            out.append(resp["embeddings"][0])
        return out

    def ingest(
        self,
        files: Iterable[str | Path],
        *,
        project_id: str = "",
        agent_id: str = "",
        source_label: str = "",
    ) -> dict[str, int]:
        """Embed + store every chunk of every file. Returns counts."""
        stats = {"files": 0, "chunks": 0}
        for path in files:
            p = Path(path)
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            chunks = _chunk_text(text)
            if not chunks:
                continue
            vectors = self._embed(chunks)
            src = source_label or str(p)
            points = []
            for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                point_id = hashlib.sha256(f"{src}:{i}".encode()).hexdigest()[:32]
                points.append(
                    PointStruct(
                        id=point_id,
                        vector=vec,
                        payload={
                            "source": src,
                            "project_id": project_id,
                            "agent_id": agent_id,
                            "chunk_index": i,
                            "text": chunk,
                        },
                    )
                )
                self.registry.record(
                    point_id,
                    chunk[:500],
                    project_id=project_id,
                    agent_id=agent_id,
                    source=src,
                    confidence=1.0,
                    evidence=f"{src}#chunk{i}",
                )
            self.qdrant.upsert(collection_name=self.collection, points=points)
            stats["files"] += 1
            stats["chunks"] += len(chunks)
        return stats

    def search(self, query: str, limit: int = 5) -> list[dict]:
        vec = self._embed([query])[0]
        hits = self.qdrant.query_points(
            collection_name=self.collection,
            query=vec,
            limit=limit,
        )
        return [
            {
                "id": h.id,
                "score": h.score,
                "source": h.payload.get("source"),
                "project_id": h.payload.get("project_id"),
                "text": h.payload.get("text"),
            }
            for h in hits.points
        ]