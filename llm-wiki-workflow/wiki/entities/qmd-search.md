---
title: qmd (Markdown Search)
type: entity
sources:
  - raw/articles/karpathy-llm-wiki-complete-guide.md
related:
  - wiki/concepts/llm-wiki-workflow.md
  - wiki/concepts/retrieval-augmented-generation.md
  - wiki/entities/obsidian.md
  - wiki/sources/karpathy-llm-wiki-complete-guide.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Local markdown search engine by Tobi Lutke (Shopify CEO) combining BM25 keyword search, vector semantic search, and LLM re-ranking — all on-device via node-llama-cpp.
---

# qmd (Markdown Search)

Local search engine for markdown files that combines BM25 full-text search, vector semantic search, and LLM re-ranking, all running on-device with no cloud API calls.

## Background

Built by Tobi Lutke (CEO of Shopify). Designed specifically for searching collections of markdown files — exactly the use case of the [[concepts/llm-wiki-workflow]]. Runs locally via `node-llama-cpp` with GGUF models.

Three search modes:

- **BM25** (`qmd search`) — keyword matching, fast and precise
- **Vector** (`qmd vsearch`) — semantic matching, finds related concepts even without exact keywords
- **Hybrid + LLM re-ranking** (`qmd query`) — combines both, then an LLM scores results for relevance; highest quality

Also exposes an MCP server (`qmd mcp`) so Claude Code and other agents can use it as a native tool.

```bash
npm install -g @tobilu/qmd
qmd collection add ./wiki --name my-research
qmd search "ingest workflow"
qmd vsearch "how do I compile sources into pages"
qmd query "what are the tradeoffs of wiki vs RAG" --json
qmd mcp
```

## Relevance

At small wiki scale (~50 pages), `wiki/index.md` read by the LLM is sufficient for retrieval — no qmd needed. As the wiki grows toward hundreds of pages, the index becomes too large to read in one context window. qmd fills that gap: the LLM calls `qmd query` to find relevant pages before reading them.

Karpathy mentioned qmd as the recommended local search solution: "it's a good option for local search over markdown files with hybrid BM25/vector search and LLM re-ranking, all on-device."

The MCP server mode makes qmd directly usable inside Claude Code as a first-class tool, so the agent can search the wiki without reading the full index.
