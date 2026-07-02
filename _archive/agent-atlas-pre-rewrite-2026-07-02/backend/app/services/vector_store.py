"""
Local vector store backed by ChromaDB (embedded, no server needed).
Uses LM Studio / Ollama embedding endpoint when available; falls back to
ChromaDB's default sentence-transformers embedder otherwise.
Falls back gracefully if chromadb is not installed at all.
"""
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import httpx

logger = logging.getLogger("agent_atlas.vectorstore")

EMBED_DIR = Path(__file__).parent.parent.parent.parent / "data" / "embeddings"

_EMBEDDING_ENDPOINT = os.getenv("EMBEDDING_ENDPOINT", "http://127.0.0.1:1234/v1/embeddings")
_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5")


class _LMStudioEmbeddingFunction:
    """ChromaDB-compatible embedding function that calls any OpenAI-compatible /v1/embeddings."""

    def name(self) -> str:
        return "lmstudio"

    def _embed(self, texts: List[str]) -> List[List[float]]:
        try:
            resp = httpx.post(
                _EMBEDDING_ENDPOINT,
                json={"model": _EMBEDDING_MODEL, "input": texts},
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]
        except Exception as exc:
            logger.warning("Embedding request failed (%s) — using zero vectors", exc)
            return [[0.0] * 768 for _ in texts]

    def __call__(self, input: List[str]) -> List[List[float]]:  # noqa: A002
        return self._embed(input)

    def embed_documents(self, input: List[str]) -> List[List[float]]:  # noqa: A002
        return self._embed(input)

    def embed_query(self, input: List[str]) -> List[List[float]]:  # noqa: A002
        return self._embed(input)


_embedding_fn: Any = None
_embedding_fn_initialized: bool = False


def _get_embedding_fn():
    global _embedding_fn, _embedding_fn_initialized
    if _embedding_fn_initialized:
        return _embedding_fn   # may be None (ChromaDB default) or a custom fn

    # Check if the LM Studio embedding endpoint is reachable
    try:
        httpx.get(_EMBEDDING_ENDPOINT.replace("/embeddings", "/models"), timeout=2.0)
        _embedding_fn = _LMStudioEmbeddingFunction()
        logger.info("Using LM Studio embeddings at %s", _EMBEDDING_ENDPOINT)
    except Exception:
        # Fall back to ChromaDB default (sentence-transformers if installed).
        # _embedding_fn stays None, which signals ChromaDB to use its own embedder.
        logger.info("LM Studio embedding endpoint not reachable — using ChromaDB default embedder")

    _embedding_fn_initialized = True
    return _embedding_fn


def _get_client():
    try:
        import chromadb
        return chromadb.PersistentClient(path=str(EMBED_DIR))
    except ImportError:
        logger.warning("chromadb not installed — vector store disabled. pip install chromadb")
        return None


_client = None


def _client_lazy():
    global _client
    if _client is None:
        _client = _get_client()
    return _client


def add_documents(collection: str, docs: List[Dict[str, Any]]):
    """docs: list of {id, text, metadata}"""
    c = _client_lazy()
    if not c:
        return
    ef = _get_embedding_fn()
    col = c.get_or_create_collection(collection, embedding_function=ef)
    col.upsert(
        ids=[d["id"] for d in docs],
        documents=[d["text"] for d in docs],
        metadatas=[d.get("metadata", {}) for d in docs],
    )
    logger.debug("Added %d docs to collection '%s'", len(docs), collection)


def query(collection: str, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
    c = _client_lazy()
    if not c:
        return []
    try:
        ef = _get_embedding_fn()
        col = c.get_collection(collection, embedding_function=ef)
    except Exception:
        return []
    results = col.query(query_texts=[query_text], n_results=top_k)
    output = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    for i, doc_id in enumerate(ids):
        output.append(
            {
                "id": doc_id,
                "text": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "score": 1.0 - (distances[i] if i < len(distances) else 1.0),
            }
        )
    return output
