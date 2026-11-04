---
title: "Atlas: Retrieval Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-knowledge-hub.md
  - wiki/concepts/layered-agent-architecture.md
  - wiki/concepts/retrieval-augmented-generation.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Queries the ChromaDB vector store for semantically relevant documents. Handles non-Obsidian knowledge (ingested docs, code snippets, raw data).
---

# Atlas: Retrieval Agent

**Layer:** Knowledge | **ID:** `retrieval_agent`

The Retrieval Agent queries the ChromaDB vector store for documents that were embedded at ingest time. It handles everything that isn't in Obsidian — uploaded documents, code snippets, raw data files, and web content.

## Responsibilities

1. Receive a search query from the Knowledge Hub
2. Embed the query using `nomic-embed-text-v1.5`
3. Query ChromaDB for top-k nearest neighbors
4. Apply optional metadata filters (date, type, source)
5. Return ranked results with excerpts

## Search flow

```python
async def handle(self, message):
    query = message.payload["query"]
    top_k = message.payload.get("top_k", 5)
    embedding = await embed_query(query)
    results = chroma_collection.query(
        query_embeddings=[embedding],
        n_results=top_k,
        where=message.payload.get("filter")  # optional metadata filter
    )
    return format_results(results)
```

## ChromaDB collection

Documents are embedded and stored when:
- A file is ingested via `agent-cli ingest`
- A URL is fetched via `web_fetch` MCP tool
- Obsidian vault is re-indexed

**Embedding model:** `text-embedding-nomic-embed-text-v1.5` via LM Studio local endpoint.

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `query`, `top_k` (default 5), `filter` (optional metadata) |
| **Outputs** | List of `{id, text, score, metadata}` |
| **Message type** | `search_request` |

## Connections
- Called by: [[entities/atlas-knowledge-hub]] (in parallel with Obsidian Brain)
- Vector store populated by: ingest pipeline, Obsidian indexer
