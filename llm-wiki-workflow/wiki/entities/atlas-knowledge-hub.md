---
title: "Atlas: Knowledge Hub Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-retrieval-agent.md
  - wiki/entities/atlas-obsidian-brain.md
  - wiki/entities/atlas-memory-agent.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Fan-out knowledge retrieval coordinator — runs ChromaDB vector search and Obsidian vault search in parallel and returns a merged evidence pack.
---

# Atlas: Knowledge Hub Agent

**Layer:** Knowledge | **ID:** `knowledge_hub`

The Knowledge Hub is the single entry point for all information retrieval. Instead of making callers know about ChromaDB vs. Obsidian, it fans out to both in parallel and merges results into an evidence pack.

## Responsibilities

1. Receive a research request from the Orchestrator
2. Run **Retrieval Agent** (ChromaDB vector search) and **Obsidian Brain** (vault search) in parallel via `asyncio.gather`
3. Merge, deduplicate, and rank results
4. Return a unified evidence pack

## Fan-out pattern

```python
async def handle(self, message):
    query = message.payload["query"]
    retrieval_result, obsidian_result = await asyncio.gather(
        bus.send_message(from_agent="knowledge_hub", to_agent="retrieval_agent",
                         msg_type="search_request", payload={"query": query}),
        bus.send_message(from_agent="knowledge_hub", to_agent="obsidian_brain",
                         msg_type="obsidian_search", payload={"query": query}),
    )
    return merge_evidence(retrieval_result, obsidian_result)
```

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `query`, `context`, `top_k` |
| **Outputs** | `evidence_pack` (list of ranked results with source labels) |
| **Message type** | `research_request` |

## Evidence pack format

```json
{
  "results": [
    {"source": "chromadb", "text": "...", "score": 0.92, "metadata": {...}},
    {"source": "obsidian", "text": "...", "path": "Atlas/Knowledge/concepts/rag.md", "score": 0.87}
  ]
}
```

## Why this matters for the LLM Wiki

All wiki pages synced to `Atlas/Knowledge/` in Obsidian are searchable via this agent. When you ingest a raw source into the LLM Wiki, that knowledge becomes accessible to every Agent Atlas task through the Knowledge Hub.

## Connections
- Delegates to: [[entities/atlas-retrieval-agent]], [[entities/atlas-obsidian-brain]]
- Called by: [[entities/atlas-orchestrator]], [[entities/atlas-background-runtime]]
