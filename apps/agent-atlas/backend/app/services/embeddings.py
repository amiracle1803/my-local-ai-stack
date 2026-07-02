"""
embeddings.py  --  Turn text into a vector using Ollama's embedding model.

No chromadb/vector-DB dependency: nomic-embed-text is already the
embedding model this whole stack standardizes on (see config.json's
embed_model), so this just calls Ollama's native /api/embeddings
endpoint and stores the float list as JSON. Cosine similarity is plain
Python -- a personal Obsidian vault is a few hundred to a few thousand
notes, not a scale where brute-force search needs a specialized index.
"""

import math
import os
from typing import List, Optional

import httpx

OLLAMA_URL = os.getenv("AGENT_ATLAS_OLLAMA_NATIVE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("AGENT_ATLAS_EMBED_MODEL", "nomic-embed-text")


async def embed(text: str) -> Optional[List[float]]:
    """Return an embedding vector, or None if Ollama/the model isn't available."""
    if not text.strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text[:8000]},
            )
            resp.raise_for_status()
            data = resp.json()
        vec = data.get("embedding")
        return vec if isinstance(vec, list) and vec else None
    except Exception:  # noqa: BLE001
        return None


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
