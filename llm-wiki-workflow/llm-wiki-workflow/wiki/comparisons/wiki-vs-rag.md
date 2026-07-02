---
title: Maintained Wiki vs. Vector RAG
type: comparison
sources:
  - raw/articles/karpathy-llm-wiki-complete-guide.md
related:
  - wiki/concepts/llm-wiki-workflow.md
  - wiki/concepts/retrieval-augmented-generation.md
  - wiki/sources/karpathy-llm-wiki-complete-guide.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Full tradeoff comparison between a curated LLM-maintained markdown wiki and a vector-index RAG pipeline across seven dimensions.
---

# Maintained Wiki vs. Vector RAG

Comparing [[concepts/llm-wiki-workflow]] against [[concepts/retrieval-augmented-generation]] across the dimensions that matter for personal and team knowledge bases.

## Dimensions

Seven dimensions derived from Karpathy's analysis and the Agentpedia guide:

1. **When knowledge is processed** — at ingest time vs. at query time
2. **Cross-references** — pre-built vs. discovered ad-hoc
3. **Contradictions** — flagged on ingest vs. potentially missed
4. **Knowledge accumulation** — compounds vs. resets each query
5. **Output format** — durable markdown vs. ephemeral chat
6. **Transparency** — human-readable vs. black-box embeddings
7. **Infrastructure** — zero vs. requires embedding + index stack

## Analysis

| Dimension | Traditional RAG | LLM Wiki |
| --- | --- | --- |
| When knowledge is processed | At query time (every question) | At ingest time (once per source) |
| Cross-references | Discovered ad-hoc per query | Pre-built and maintained |
| Contradictions | May not be noticed | Flagged during ingestion |
| Knowledge accumulation | None — starts fresh each query | Compounds with every source and query |
| Output format | Chat responses (ephemeral) | Persistent markdown files (durable) |
| Who maintains it | The system (black box) | The LLM (transparent, editable) |
| Human role | Upload and query | Curate, explore, and question |
| Setup complexity | Requires embedding pipeline + vector DB | Plain markdown + schema file |
| Scale ceiling | Millions of documents | ~hundreds of pages (then add qmd) |
| Examples | NotebookLM, ChatGPT uploads | Karpathy's LLM Wiki pattern |

### RAG strengths

- Scales to millions of documents without manual curation
- Works well for large, fast-growing corpora
- No per-document LLM cost at ingest time
- Near-instant setup for a new document collection

### Wiki strengths

- Human-readable, diff-able, version-controlled in git
- No embedding or vector database infrastructure required
- Cross-references, contradictions, and gaps are surfaced proactively
- Every ingest and query compounds the value of the knowledge base
- Answers are durable wiki artifacts, not ephemeral chat responses
- The schema file carries consistent conventions across sessions

### The compounding loop

Sources are ingested → queries generate insights → best insights are filed back as wiki pages. The wiki grows from both external sources and internal exploration. RAG has no equivalent feedback loop.

### Index.md as lightweight retrieval

At moderate scale (~100 sources, ~hundreds of pages), a well-maintained `index.md` + LLM reading is enough for high-quality retrieval. This avoids the embedding/index stack entirely. For larger wikis, tools like `qmd` add BM25 + vector + LLM re-ranking on-device.

## Takeaway

For a **focused personal or team knowledge base** where depth and traceability matter, a maintained wiki is simpler, more transparent, and compounding. For **large or fast-growing corpora** (thousands of documents) where setup speed matters more than depth, vector RAG scales better.

The systems are not mutually exclusive: a wiki can add `qmd` for search as it grows, and a RAG system can adopt wiki-style curation for high-value documents.
